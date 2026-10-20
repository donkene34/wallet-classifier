"""Feature engineering : historique de transactions d'un wallet -> 8 features comportementales.

Usage :
    python features.py             # construit data/features.csv depuis data/labels.csv
    python features.py --offline   # n'appelle jamais Etherscan : cache uniquement (même ancien)
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import collector
from collect_labels import LABELS_PATH, load_labels
from collector import EtherscanError, get_wallet_transactions

MIN_TX = 10  # en dessous, une analyse comportementale n'est pas fiable
FEATURES_PATH = LABELS_PATH.with_name("features.csv")
ROUND_DECIMALS = 4  # un montant est "rond" s'il n'a pas plus de 4 décimales (0.1, 0.25, 2...)

FEATURE_COLUMNS = [
    "tx_count",
    "avg_time_between_tx",
    "std_time_between_tx",
    "hour_entropy",
    "gas_price_std",
    "unique_contracts_ratio",
    "round_amount_ratio",
    "weekend_ratio",
]


class NotEnoughTransactions(ValueError):
    """Pas assez de transactions pour calculer des features fiables."""

    def __init__(self, n: int, min_tx: int):
        super().__init__(f"{n} transaction(s) sur la période, minimum {min_tx} pour une analyse fiable")
        self.n = n
        self.min_tx = min_tx


def _std(values: np.ndarray) -> float:
    return float(np.std(values, ddof=1)) if len(values) > 1 else 0.0


def compute_features(txs: pd.DataFrame, min_tx: int = MIN_TX) -> dict[str, float]:
    """Calcule les 8 features à partir du DataFrame renvoyé par `get_wallet_transactions`.

    - tx_count               : nombre de transactions sortantes sur la période
    - avg_time_between_tx    : intervalle moyen entre deux tx (secondes)
    - std_time_between_tx    : écart-type de cet intervalle (un bot régulier -> proche de 0)
    - hour_entropy           : entropie de Shannon (bits, UTC) de la répartition sur les 24 heures
                               (max = log2(24) ~ 4.585 pour une activité uniforme 24/7)
    - gas_price_std          : écart-type du gas price payé (gwei)
    - unique_contracts_ratio : contrats distincts appelés / nombre total de tx
    - round_amount_ratio     : part de montants "ronds" parmi les tx qui transfèrent de l'ETH
                               (value > 0) ; 0.0 si le wallet n'envoie jamais d'ETH
    - weekend_ratio          : part des tx faites un samedi ou un dimanche (UTC)

    Lève NotEnoughTransactions si le wallet a moins de `min_tx` transactions (3 au minimum).
    """
    n = len(txs)
    if n < max(min_tx, 3):
        raise NotEnoughTransactions(n, min_tx)

    gaps = np.diff(np.sort(txs["timestamp"].to_numpy(dtype="int64")))

    when = pd.to_datetime(txs["timestamp"], unit="s", utc=True)
    hour_counts = np.bincount(when.dt.hour.to_numpy(), minlength=24)
    p = hour_counts[hour_counts > 0] / n
    hour_entropy = float(-(p * np.log2(p)).sum())

    calls = txs[txs["is_contract_call"] == 1]["to_address"].replace("", np.nan).dropna()
    unique_contracts_ratio = calls.nunique() / n

    sent = txs.loc[txs["value_eth"] > 0, "value_eth"]
    if len(sent):
        scaled = sent * 10**ROUND_DECIMALS
        round_amount_ratio = float(((scaled - scaled.round()).abs() < 1e-6).mean())
    else:
        round_amount_ratio = 0.0

    return {
        "tx_count": n,
        "avg_time_between_tx": float(gaps.mean()),
        "std_time_between_tx": _std(gaps),
        "hour_entropy": hour_entropy,
        "gas_price_std": _std(txs["gas_price_gwei"].to_numpy(dtype="float64")),
        "unique_contracts_ratio": float(unique_contracts_ratio),
        "round_amount_ratio": round_amount_ratio,
        "weekend_ratio": float((when.dt.dayofweek >= 5).mean()),
    }


def build_feature_table(labels: pd.DataFrame, loader, min_tx: int = MIN_TX):
    """Une ligne par wallet utilisable. `loader(address)` renvoie le DataFrame de tx (ou None).

    Retourne (table, skipped) où skipped = [(adresse, raison), ...].
    """
    rows, skipped = [], []
    for _, r in labels.iterrows():
        txs = loader(r["address"])
        if txs is None:
            skipped.append((r["address"], "transactions indisponibles (cache vide ou erreur Etherscan)"))
            continue
        try:
            feats = compute_features(txs, min_tx)
        except NotEnoughTransactions as exc:
            skipped.append((r["address"], str(exc)))
            continue
        rows.append({"address": r["address"], "label": r["label"], "category": r["category"], **feats})
    return pd.DataFrame(rows, columns=["address", "label", "category", *FEATURE_COLUMNS]), skipped


def _make_loader(days: int, offline: bool):
    if offline:
        collector.CACHE_TTL_SECONDS = 10**9  # accepte un cache de n'importe quel âge
        return lambda addr: collector._read_cache(addr, days)

    def online(addr: str):
        try:
            return get_wallet_transactions(addr, days=days)
        except (EtherscanError, ValueError):
            return None

    return online


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--min-tx", type=int, default=MIN_TX)
    ap.add_argument("--offline", action="store_true", help="cache uniquement, aucun appel Etherscan")
    ap.add_argument("--verified-only", action="store_true", help="exclure status=a_verifier")
    args = ap.parse_args()

    labels = load_labels(include_unverified=not args.verified_only)
    print(f"{len(labels)} wallets dans labels.csv")
    table, skipped = build_feature_table(labels, _make_loader(args.days, args.offline), args.min_tx)

    table.to_csv(FEATURES_PATH, index=False)
    print(f"{len(table)} wallets utilisables, {len(skipped)} écartés -> {FEATURES_PATH.name}")
    print(table["label"].value_counts().to_string())
    if not table.empty:
        print("\nMoyenne des features par classe :")
        print(table.groupby("label")[FEATURE_COLUMNS].mean().round(3).T.to_string())
