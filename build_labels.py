"""Remplit data/labels.csv avec des adresses récupérées via des API publiques gratuites.

- humains : votants récents de DAO sur Snapshot (API GraphQL publique, sans clé)
- bots    : transactions d'extraction MEV (frontrun/backrun/arb/liquid) vues par ZeroMEV
            (API publique, sans clé) -> `address_from` = l'EOA qui envoie la tx

Usage :
    python build_labels.py --dry-run     # affiche ce qui serait ajouté, n'écrit rien
    python build_labels.py               # ajoute les adresses à data/labels.csv
Les nouvelles lignes ont status=a_verifier ; les lignes existantes ne sont jamais modifiées.
"""

from __future__ import annotations

import argparse
import random
import time
from collections import Counter
from pathlib import Path

import pandas as pd
import requests
from web3 import Web3

from collector import _block_at

LABELS_PATH = Path(__file__).parent / "data" / "labels.csv"
COLUMNS = ["address", "label", "category", "source", "status"]

SNAPSHOT_URL = "https://hub.snapshot.org/graphql"
SNAPSHOT_SPACES = ["ens.eth", "gitcoindao.eth", "uniswapgovernance.eth"]

ZEROMEV_URL = "https://data.zeromev.org/v1/mevBlock"
# Dans ZeroMEV, "sandwich" désigne la tx de la VICTIME : on l'exclut volontairement.
BOT_MEV_TYPES = {"frontrun", "backrun", "arb", "liquid"}


# --------------------------------------------------------------------------- #
# Humains : votants Snapshot
# --------------------------------------------------------------------------- #
def _gql(query: str) -> dict:
    r = requests.post(SNAPSHOT_URL, json={"query": query}, timeout=30)
    r.raise_for_status()
    body = r.json()
    if "errors" in body:
        raise RuntimeError(f"Snapshot a renvoyé une erreur : {body['errors']}")
    return body["data"]


def fetch_voters(per_space: int = 50, proposals: int = 6) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for space in SNAPSHOT_SPACES:
        kept = 0
        props = _gql(
            f'{{ proposals(first:{proposals}, where:{{space:"{space}", state:"closed"}}, '
            'orderBy:"created", orderDirection:desc){ id } }'
        )["proposals"]
        for p in props:
            votes = _gql(
                f'{{ votes(first:100, where:{{proposal:"{p["id"]}"}}, '
                'orderBy:"vp", orderDirection:desc){ voter } }'
            )["votes"]
            for v in votes:
                addr = v["voter"].lower()
                if kept >= per_space:
                    break
                if addr in seen or not Web3.is_address(addr):
                    continue
                seen.add(addr)
                kept += 1
                rows.append(
                    {
                        "address": addr,
                        "label": "human",
                        "category": "dao_voter",
                        "source": f"Snapshot - votant récent de {space}",
                        "status": "a_verifier",
                    }
                )
        print(f"  {space}: {kept} votants")
    return rows


# --------------------------------------------------------------------------- #
# Bots : extracteurs MEV (ZeroMEV)
# --------------------------------------------------------------------------- #
def fetch_mev_bots(n: int = 60, days: int = 30, samples: int = 80, seed: int = 42) -> list[dict]:
    now = int(time.time())
    lo, hi = _block_at(now - days * 86400), _block_at(now)
    rng = random.Random(seed)
    counts: Counter[str] = Counter()
    types_seen: Counter[str] = Counter()
    keys_printed = False
    errors = 0
    first_error = ""

    for block in rng.sample(range(lo, hi), min(samples, hi - lo)):
        time.sleep(0.3)
        try:
            resp = requests.get(ZEROMEV_URL, params={"block_number": block}, timeout=30)
            resp.raise_for_status()
            entries = resp.json()
        except (requests.RequestException, ValueError) as exc:
            errors += 1
            first_error = first_error or f"bloc {block}: {exc}"
            continue
        for e in entries or []:
            if not keys_printed:
                print("  champs ZeroMEV :", sorted(e.keys()))
                keys_printed = True
            types_seen[str(e.get("mev_type"))] += 1
            addr = (e.get("address_from") or "").lower()
            if e.get("mev_type") in BOT_MEV_TYPES and Web3.is_address(addr):
                counts[addr] += 1

    print("  types MEV vus :", dict(types_seen))
    if errors:
        print(f"  {errors}/{samples} requêtes en erreur ; première : {first_error}")
    if not counts:
        raise RuntimeError(
            "Aucune adresse de bot trouvée : l'API ZeroMEV a peut-être changé "
            "(vérifie les champs affichés ci-dessus)."
        )
    return [
        {
            "address": addr,
            "label": "bot",
            "category": "mev_extractor",
            "source": f"ZeroMEV - {c} tx d'extraction MEV sur l'échantillon",
            "status": "a_verifier",
        }
        for addr, c in counts.most_common(n)
    ]


# --------------------------------------------------------------------------- #
# Fusion
# --------------------------------------------------------------------------- #
def merge(existing: pd.DataFrame, new_rows: list[dict]) -> pd.DataFrame:
    """Ajoute les nouvelles lignes sans toucher aux existantes ni créer de doublon."""
    known = {Web3.to_checksum_address(a).lower() for a in existing["address"]}
    add = [r for r in new_rows if r["address"] not in known]
    return pd.concat([existing, pd.DataFrame(add, columns=COLUMNS)], ignore_index=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--humans", type=int, default=50, help="votants par DAO")
    ap.add_argument("--bots", type=int, default=60)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--skip-bots", action="store_true", help="ne récupérer que les humains")
    args = ap.parse_args()

    print("Votants Snapshot...")
    humans = fetch_voters(per_space=args.humans)
    bots: list[dict] = []
    if not args.skip_bots:
        print("Extracteurs MEV (ZeroMEV)...")
        bots = fetch_mev_bots(n=args.bots, days=args.days)

    existing = pd.read_csv(LABELS_PATH, dtype=str).fillna("")
    merged = merge(existing, humans + bots)
    added = merged.iloc[len(existing):]
    print(f"\n{len(added)} nouvelles adresses ({added['label'].value_counts().to_dict()}).")
    print(added.head(8)[["address", "label", "category"]].to_string(index=False))

    if args.dry_run:
        print("\n--dry-run : rien n'a été écrit.")
    else:
        merged.to_csv(LABELS_PATH, index=False)
        print(f"\nÉcrit dans {LABELS_PATH}. Étape suivante : python collect_labels.py --all")
