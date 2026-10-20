"""Découvre des EOA de bots via Etherscan (heuristique structurelle, sans autre source).

Idée : un humain passe par un routeur public et vérifié. Un bot MEV/arbitrage appelle
directement les pools depuis son propre contrat NON VÉRIFIÉ et peu appelé. On :
  1. liste les contreparties récentes de gros pools Uniswap (transferts de tokens),
  2. garde celles qui sont des contrats non vérifiés,
  3. garde ceux qui ne sont appelés que par quelques EOA (contrat "privé"),
  4. retourne ces EOA comme bots candidats (status=a_verifier).

Heuristique : peut produire des faux positifs (contrat privé non-bot). C'est un POC.

Usage :
    python discover_bots.py --dry-run
    python discover_bots.py
"""

from __future__ import annotations

import argparse
from collections import Counter

import pandas as pd
from web3 import Web3

from build_labels import COLUMNS, LABELS_PATH, merge
from collector import _call

POOLS = {
    "Uniswap V3 USDC/WETH 0.05%": "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640",
    "Uniswap V3 WETH/USDT 0.3%": "0x4e68Ccd3E89f51C3074ca5072bbAC773960dFa36",
}
MAX_CALLERS = 5      # un contrat appelé par plus d'EOA que ça n'est pas "privé"
MIN_CALLS = 5        # il faut une activité minimale pour parler de bot
MIN_CALLER_TX = 3    # un EOA doit avoir appelé le contrat au moins N fois


def counterparties(pool: str, n_transfers: int) -> Counter:
    data = _call(
        {"module": "account", "action": "tokentx", "address": pool,
         "page": 1, "offset": n_transfers, "sort": "desc"}
    )
    result = data.get("result")
    if not isinstance(result, list):
        raise RuntimeError(f"tokentx a échoué pour {pool} : {data.get('message')} - {result}")
    pool_l = pool.lower()
    c: Counter = Counter()
    for t in result:
        for side in (t["from"].lower(), t["to"].lower()):
            if side != pool_l:
                c[side] += 1
    return c


def is_unverified_contract(addr: str) -> bool:
    code = _call({"module": "proxy", "action": "eth_getCode", "address": addr, "tag": "latest"})
    if code.get("result") in (None, "", "0x"):
        return False  # EOA
    src = _call({"module": "contract", "action": "getsourcecode", "address": addr})
    res = src.get("result")
    entry = res[0] if isinstance(res, list) and res else {}
    return not entry.get("SourceCode")


def callers_of(contract: str) -> Counter:
    data = _call(
        {"module": "account", "action": "txlist", "address": contract, "startblock": 0,
         "endblock": 99_999_999, "page": 1, "offset": 200, "sort": "desc"}
    )
    result = data.get("result")
    c: Counter = Counter()
    if isinstance(result, list):
        for tx in result:
            if tx["to"].lower() == contract and tx.get("isError") == "0":
                c[tx["from"].lower()] += 1
    return c


def discover(top_n: int = 60, n_transfers: int = 2000) -> list[dict]:
    rows: list[dict] = []
    seen_eoa: set[str] = set()
    for name, pool in POOLS.items():
        cp = counterparties(pool, n_transfers)
        candidates = [a for a, _ in cp.most_common(top_n)]
        unverified = [a for a in candidates if is_unverified_contract(a)]
        print(f"  {name}: {len(cp)} contreparties, top {len(candidates)} testées, "
              f"{len(unverified)} contrats non vérifiés")
        private = 0
        for contract in unverified:
            callers = callers_of(contract)
            if not (0 < len(callers) <= MAX_CALLERS) or sum(callers.values()) < MIN_CALLS:
                continue
            private += 1
            for eoa, n in callers.items():
                if n >= MIN_CALLER_TX and eoa not in seen_eoa and Web3.is_address(eoa):
                    seen_eoa.add(eoa)
                    rows.append(
                        {
                            "address": eoa,
                            "label": "bot",
                            "category": "private_contract_caller",
                            "source": f"Etherscan - appelle {n}x le contrat privé non vérifié "
                                      f"{contract} (lié à {name})",
                            "status": "a_verifier",
                        }
                    )
        print(f"    -> {private} contrats privés, {len(rows)} EOA candidats au total")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--top", type=int, default=60, help="contreparties testées par pool")
    args = ap.parse_args()

    print("Découverte de bots via Etherscan (ça prend quelques minutes)...")
    bots = discover(top_n=args.top)
    if not bots:
        raise SystemExit("Aucun candidat trouvé : augmente --top ou colle-moi la sortie.")

    existing = pd.read_csv(LABELS_PATH, dtype=str).fillna("")
    merged = merge(existing, bots)
    added = merged.iloc[len(existing):]
    print(f"\n{len(added)} nouveaux bots candidats.")
    print(added.head(10)[["address", "category"]].to_string(index=False))
    if args.dry_run:
        print("\n--dry-run : rien n'a été écrit.")
    else:
        merged.to_csv(LABELS_PATH, index=False)
        print(f"\nÉcrit dans {LABELS_PATH}.")
