"""Collecte des transactions Ethereum d'une adresse via Etherscan V2, avec cache SQLite."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

ETHERSCAN_URL = "https://api.etherscan.io/v2/api"
CHAIN_ID = 1  # Ethereum mainnet
PAGE_SIZE = 1_000  # plafond observé par appel (plan gratuit) ; on pagine par bloc au-delà
MAX_PAGES = 20  # garde-fou : ~20 000 lignes max par wallet (au-delà on garde le début de la période)
VERBOSE = False  # affiche la progression de la pagination (activé par collect_labels.py)
REQUEST_DELAY = 0.35  # ~3 req/s (limite du plan gratuit)
CACHE_TTL_SECONDS = 24 * 3600
# cache_v2 : l'ancien cache.db contient des historiques tronqués à ~1000 tx, on l'ignore
DB_PATH = Path(__file__).parent / "data" / "cache_v2.db"

COLUMNS = [
    "hash",
    "block_number",
    "timestamp",
    "from_address",
    "to_address",
    "value_eth",
    "gas_price_gwei",
    "gas_used",
    "is_error",
    "is_contract_call",
]


class EtherscanError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Etherscan
# --------------------------------------------------------------------------- #
def _api_key() -> str:
    key = os.getenv("ETHERSCAN_API_KEY")
    if not key:
        raise EtherscanError("ETHERSCAN_API_KEY manquante (voir .env.example).")
    return key


def _call(params: dict) -> dict:
    """Appel Etherscan V2 avec rate limit et un retry simple sur limite de débit."""
    params = {**params, "chainid": CHAIN_ID, "apikey": _api_key()}
    last_error = "limite de débit Etherscan dépassée"
    for attempt in range(4):
        time.sleep(REQUEST_DELAY)
        try:
            resp = requests.get(ETHERSCAN_URL, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:  # timeout, coupure, JSON invalide
            last_error = f"erreur réseau : {exc}"
            time.sleep(2 * (attempt + 1))
            continue
        result = data.get("result")
        if isinstance(result, str) and "rate limit" in result.lower():
            last_error = "limite de débit Etherscan dépassée"
            time.sleep(1.5 * (attempt + 1))
            continue
        return data
    raise EtherscanError(f"Etherscan injoignable après 4 essais ({last_error}).")


def _block_at(timestamp: int) -> int:
    data = _call(
        {
            "module": "block",
            "action": "getblocknobytime",
            "timestamp": timestamp,
            "closest": "before",
        }
    )
    if data.get("status") != "1":
        raise EtherscanError(f"getblocknobytime a échoué : {data.get('result')}")
    return int(data["result"])


def _fetch_raw(address: str, start_block: int) -> list[dict]:
    """Récupère toutes les tx normales de `address` depuis `start_block` (ordre croissant)."""
    raw: list[dict] = []
    seen: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        data = _call(
            {
                "module": "account",
                "action": "txlist",
                "address": address,
                "startblock": start_block,
                "endblock": 99_999_999,
                "page": 1,
                "offset": PAGE_SIZE,
                "sort": "asc",
            }
        )
        result = data.get("result")
        if data.get("status") != "1":
            if isinstance(result, list) or "no transactions" in str(data.get("message", "")).lower():
                break  # aucune transaction
            raise EtherscanError(f"txlist a échoué : {data.get('message')} - {result}")
        new = [tx for tx in result if tx["hash"] not in seen]
        seen.update(tx["hash"] for tx in new)
        raw.extend(new)
        if len(result) < PAGE_SIZE or not new:
            break
        if VERBOSE:
            print(f"[p{page}:{len(raw)}]", end=" ", flush=True)
        # page pleine : on repart du dernier bloc (les doublons sont écartés via `seen`)
        start_block = int(result[-1]["blockNumber"])
    else:  # MAX_PAGES atteint sans avoir épuisé l'historique
        if VERBOSE:
            print("[plafonné]", end=" ", flush=True)
    return raw


def _to_dataframe(raw: list[dict], address: str) -> pd.DataFrame:
    """Garde les tx sortantes et normalise les colonnes."""
    addr = address.lower()
    rows = []
    for tx in raw:
        if tx.get("from", "").lower() != addr:
            continue
        rows.append(
            {
                "hash": tx["hash"],
                "block_number": int(tx["blockNumber"]),
                "timestamp": int(tx["timeStamp"]),
                "from_address": addr,
                "to_address": (tx.get("to") or "").lower(),  # vide si création de contrat
                "value_eth": int(tx["value"]) / 1e18,
                "gas_price_gwei": int(tx["gasPrice"]) / 1e9,
                "gas_used": int(tx["gasUsed"]),
                "is_error": int(tx.get("isError", "0")),
                "is_contract_call": int(tx.get("input", "0x") not in ("0x", "")),
            }
        )
    return pd.DataFrame(rows, columns=COLUMNS)


# --------------------------------------------------------------------------- #
# Cache SQLite
# --------------------------------------------------------------------------- #
def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS txs (
            address TEXT NOT NULL,
            hash TEXT NOT NULL,
            block_number INTEGER,
            timestamp INTEGER,
            from_address TEXT,
            to_address TEXT,
            value_eth REAL,
            gas_price_gwei REAL,
            gas_used INTEGER,
            is_error INTEGER,
            is_contract_call INTEGER,
            PRIMARY KEY (address, hash)
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_txs_addr_ts ON txs(address, timestamp)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS fetch_log (
            address TEXT PRIMARY KEY,
            days INTEGER NOT NULL,
            fetched_at INTEGER NOT NULL
        )"""
    )
    return conn


def _read_cache(address: str, days: int) -> pd.DataFrame | None:
    """Retourne les tx en cache si le cache est frais ET couvre au moins `days` jours."""
    now = int(time.time())
    with _connect() as conn:
        row = conn.execute(
            "SELECT days, fetched_at FROM fetch_log WHERE address = ?", (address,)
        ).fetchone()
        if row is None:
            return None
        cached_days, fetched_at = row
        if cached_days < days or now - fetched_at > CACHE_TTL_SECONDS:
            return None
        cutoff = now - days * 86400
        return pd.read_sql_query(
            f"SELECT {', '.join(COLUMNS)} FROM txs WHERE address = ? AND timestamp >= ? "
            "ORDER BY timestamp",
            conn,
            params=(address, cutoff),
        )


def _write_cache(address: str, days: int, df: pd.DataFrame) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM txs WHERE address = ?", (address,))
        if not df.empty:
            out = df.copy()
            out.insert(0, "address", address)
            out.to_sql("txs", conn, if_exists="append", index=False)
        conn.execute(
            "INSERT OR REPLACE INTO fetch_log (address, days, fetched_at) VALUES (?, ?, ?)",
            (address, days, int(time.time())),
        )


# --------------------------------------------------------------------------- #
# API publique
# --------------------------------------------------------------------------- #
def get_wallet_transactions(address: str, days: int = 90, use_cache: bool = True) -> pd.DataFrame:
    """Transactions sortantes de `address` sur les `days` derniers jours.

    Colonnes : voir COLUMNS. `is_contract_call` = 1 si la tx porte des données
    d'appel (interaction avec un contrat). Lève ValueError si l'adresse est invalide.
    """
    if not Web3.is_address(address):
        raise ValueError(f"Adresse Ethereum invalide : {address}")
    address = Web3.to_checksum_address(address).lower()

    if use_cache:
        cached = _read_cache(address, days)
        if cached is not None:
            return cached

    start_ts = int(time.time()) - days * 86400
    start_block = _block_at(start_ts)
    df = _to_dataframe(_fetch_raw(address, start_block), address)
    df = df[df["timestamp"] >= start_ts].sort_values("timestamp").reset_index(drop=True)

    if use_cache:
        _write_cache(address, days, df)
    return df


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        sys.exit("Usage : python collector.py <adresse> [jours]")
    d = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    frame = get_wallet_transactions(sys.argv[1], days=d)
    print(f"{len(frame)} transactions sortantes sur {d} jours")
    print(frame.head(10).to_string(index=False))
