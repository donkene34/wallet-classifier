"""Valide data/labels.csv puis collecte (avec cache) les transactions de chaque wallet.

Usage :
    python collect_labels.py                 # wallets status=verified uniquement
    python collect_labels.py --all           # inclut aussi status=a_verifier
    python collect_labels.py --days 90 --min-tx 10
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from web3 import Web3

import collector
from collector import EtherscanError, get_wallet_transactions

LABELS_PATH = Path(__file__).parent / "data" / "labels.csv"
REQUIRED = ["address", "label", "category", "source", "status"]
VALID_LABELS = {"bot", "human"}


def load_labels(path: Path = LABELS_PATH, include_unverified: bool = False) -> pd.DataFrame:
    """Charge et valide le CSV. Lève ValueError si le format est mauvais."""
    df = pd.read_csv(path, dtype=str).fillna("")
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"Colonnes manquantes dans {path.name} : {missing}")

    bad = df[~df["label"].isin(VALID_LABELS)]
    if not bad.empty:
        raise ValueError(f"Labels invalides (attendu bot/human) :\n{bad[['address', 'label']]}")

    invalid = [a for a in df["address"] if not Web3.is_address(a)]
    if invalid:
        raise ValueError(f"Adresses invalides : {invalid}")

    df["address"] = [Web3.to_checksum_address(a).lower() for a in df["address"]]
    dup = df[df["address"].duplicated(keep=False)]
    if not dup.empty:
        raise ValueError(f"Adresses en double :\n{dup[['address', 'label']]}")

    if not include_unverified:
        df = df[df["status"] == "verified"]
    return df.reset_index(drop=True)


def collect(df: pd.DataFrame, days: int, min_tx: int) -> pd.DataFrame:
    """Collecte chaque wallet (le cache SQLite évite de re-fetch) et résume le résultat."""
    collector.VERBOSE = True  # montre la progression des wallets à très gros historique
    rows = []
    for i, r in df.iterrows():
        print(f"[{i + 1}/{len(df)}] {r['label']:<5} {r['address']}", end=" ", flush=True)
        try:
            txs = get_wallet_transactions(r["address"], days=days)
            n, err = len(txs), ""
        except (EtherscanError, ValueError) as e:
            n, err = 0, str(e)
        usable = n >= min_tx
        print(f"-> {n} tx"
              f"{'' if usable else '  (trop peu pour entraîner)'}{'  ERREUR: ' + err if err else ''}")
        rows.append({**r.to_dict(), "tx_count": n, "usable": usable, "error": err})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--min-tx", type=int, default=10, help="seuil de tx pour garder un wallet")
    ap.add_argument("--all", action="store_true", help="inclure status=a_verifier")
    args = ap.parse_args()

    labels = load_labels(include_unverified=args.all)
    print(f"{len(labels)} wallets à collecter ({labels['label'].value_counts().to_dict()})")
    summary = collect(labels, args.days, args.min_tx)
    out = LABELS_PATH.with_name("labels_collected.csv")
    summary.to_csv(out, index=False)
    ok = summary[summary["usable"]]
    print(f"\nRésumé écrit dans {out.name} : {len(ok)}/{len(summary)} wallets utilisables "
          f"({ok['label'].value_counts().to_dict()})")
