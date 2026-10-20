"""Phase 5 : classifieur XGBoost bot vs humain.

Avec 85 wallets, un seul split train/test serait trop bruité : on évalue par validation croisée
(5 plis, répétée 5 fois, prédictions "hors pli" regroupées). Les plis sont construits par groupe
(contrat le plus appelé) quand le cache est disponible : plusieurs bots d'un même opérateur appellent
le même contrat et ne doivent pas se retrouver à la fois dans le train et dans le test.

Usage :
    python classifier.py                  # évalue (avec / sans unique_contracts_ratio) puis sauvegarde le modèle
    python classifier.py --drop unique_contracts_ratio   # entraîne le modèle final sans cette feature
"""

from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score, precision_score,
                             recall_score, roc_auc_score)
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold
from xgboost import DMatrix, XGBClassifier

import collector
from features import FEATURE_COLUMNS, FEATURES_PATH

SEED = 42
N_SPLITS = 5
N_REPEATS = 5
MODEL_PATH = Path(__file__).parent / "models" / "wallet_classifier.pkl"
THRESHOLD = 0.5


def make_model(y: np.ndarray) -> XGBClassifier:
    """Petit modèle (arbres peu profonds) : avec ~85 lignes, un gros modèle ne ferait que mémoriser."""
    pos, neg = int((y == 1).sum()), int((y == 0).sum())
    return XGBClassifier(
        n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
        min_child_weight=1, reg_lambda=1.0,
        scale_pos_weight=neg / max(pos, 1),  # compense le déséquilibre humains/bots
        eval_metric="logloss", random_state=SEED, n_jobs=1,
    )


def load_data(path: Path):
    df = pd.read_csv(path)
    y = (df["label"] == "bot").astype(int).to_numpy()
    if y.sum() < 5 or (1 - y).sum() < 5:
        raise ValueError("Il faut au moins 5 bots et 5 humains pour entraîner/évaluer.")
    return df, y


def contract_groups(addresses, days: int = 90) -> np.ndarray | None:
    """Contrat le plus appelé par wallet, lu dans le cache (aucun appel réseau). None si pas de cache."""
    if not collector.DB_PATH.exists():
        return None
    collector.CACHE_TTL_SECONDS = 10**9
    groups, found = [], 0
    for i, addr in enumerate(addresses):
        txs = collector._read_cache(addr, days)
        top = None
        if txs is not None and len(txs):
            calls = txs.loc[txs["is_contract_call"] == 1, "to_address"]
            if len(calls):
                top = calls.value_counts().index[0]
        found += txs is not None
        groups.append(top if top else f"solo_{i}")  # sans contrat : groupe à part
    return np.array(groups) if found else None


def cross_validate(X: pd.DataFrame, y: np.ndarray, groups: np.ndarray | None) -> dict:
    """Prédictions hors pli, répétées avec plusieurs découpages ; métriques moyennées sur les répétitions."""
    reps = []
    for r in range(N_REPEATS):
        if groups is not None:
            cv = StratifiedGroupKFold(N_SPLITS, shuffle=True, random_state=SEED + r)
            splits = cv.split(X, y, groups)
        else:
            splits = StratifiedKFold(N_SPLITS, shuffle=True, random_state=SEED + r).split(X, y)
        proba = np.zeros(len(y))
        for tr, te in splits:
            proba[te] = make_model(y[tr]).fit(X.iloc[tr], y[tr]).predict_proba(X.iloc[te])[:, 1]
        pred = (proba >= THRESHOLD).astype(int)
        reps.append({
            "accuracy": accuracy_score(y, pred), "precision": precision_score(y, pred, zero_division=0),
            "recall": recall_score(y, pred), "f1": f1_score(y, pred), "roc_auc": roc_auc_score(y, proba),
            "cm": confusion_matrix(y, pred),
        })
    out = {k: float(np.mean([m[k] for m in reps])) for k in ("accuracy", "precision", "recall", "f1", "roc_auc")}
    out["accuracy_std"] = float(np.std([m["accuracy"] for m in reps]))
    out["cm"] = np.round(np.mean([m["cm"] for m in reps], axis=0)).astype(int)
    return out


def _print_cv(name: str, m: dict) -> None:
    (tn, fp), (fn, tp) = m["cm"]
    print(f"\n{name}")
    print(f"  accuracy {m['accuracy']:.2f} (±{m['accuracy_std']:.2f})  précision {m['precision']:.2f}  "
          f"rappel {m['recall']:.2f}  F1 {m['f1']:.2f}  AUC {m['roc_auc']:.2f}")
    print(f"  matrice de confusion (moyenne) : humains OK {tn}, humains pris pour bots {fp}, "
          f"bots ratés {fn}, bots trouvés {tp}")


def feature_importance(model: XGBClassifier, features: list[str]) -> pd.Series:
    return pd.Series(model.get_booster().get_score(importance_type="gain")).reindex(features).fillna(0.0) \
        .pipe(lambda s: s / s.sum() if s.sum() else s).sort_values(ascending=False)


def explain(bundle: dict, feats: dict, top: int = 3) -> list[dict]:
    """Contribution de chaque feature (SHAP natif XGBoost) à la prédiction d'un wallet.
    Positif = pousse vers 'bot', négatif = pousse vers 'humain'."""
    cols = bundle["features"]
    row = pd.DataFrame([{c: float(feats[c]) for c in cols}])
    contrib = bundle["model"].get_booster().predict(DMatrix(row), pred_contribs=True)[0][:-1]
    order = np.argsort(-np.abs(contrib))[:top]
    return [{"feature": cols[i], "value": float(row.iloc[0, i]), "contribution": float(contrib[i])}
            for i in order]


def predict_proba(bundle: dict, feats: dict) -> float:
    row = pd.DataFrame([{c: float(feats[c]) for c in bundle["features"]}])
    return float(bundle["model"].predict_proba(row)[0, 1])


def load_bundle(path: Path = MODEL_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Modèle introuvable ({path}). Lance d'abord : python classifier.py")
    return joblib.load(path)


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path, default=FEATURES_PATH)
    ap.add_argument("--model-out", type=Path, default=MODEL_PATH)
    ap.add_argument("--drop", nargs="*", default=[], help="features à exclure du modèle final")
    ap.add_argument("--no-groups", action="store_true", help="plis stratifiés simples (sans groupes par contrat)")
    args = ap.parse_args(argv)

    df, y = load_data(args.features)
    X = df[FEATURE_COLUMNS].astype(float)
    print(f"{len(df)} wallets : {int((y == 0).sum())} humains, {int(y.sum())} bots")
    print(f"Référence : toujours répondre 'humain' donne {np.mean(y == 0):.0%} d'accuracy (mais 0 % de bots trouvés).")

    groups = None if args.no_groups else contract_groups(df["address"])
    if groups is None:
        print("Validation : plis stratifiés simples (pas de cache ou --no-groups).")
    else:
        print(f"Validation : plis par groupe de contrat ({len(set(groups))} groupes) "
              f"× {N_REPEATS} répétitions.")

    results = {"all_features": cross_validate(X, y, groups)}
    _print_cv("Toutes les features", results["all_features"])
    reduced = [c for c in FEATURE_COLUMNS if c != "unique_contracts_ratio"]
    results["without_unique_contracts_ratio"] = cross_validate(X[reduced], y, groups)
    _print_cv("Sans unique_contracts_ratio", results["without_unique_contracts_ratio"])

    final_cols = [c for c in FEATURE_COLUMNS if c not in args.drop]
    if len(final_cols) < 2:
        raise ValueError("Il reste moins de 2 features.")
    model = make_model(y).fit(X[final_cols], y)
    imp = feature_importance(model, final_cols)
    print("\nImportance des features (gain, modèle final) :")
    for name, v in imp.items():
        print(f"  {name:<24} {v:6.1%}  {'#' * int(round(v * 40))}")

    bundle = {
        "model": model, "features": final_cols, "threshold": THRESHOLD,
        "importance": imp.to_dict(), "n_train": len(df), "n_bots": int(y.sum()),
        "cv": {k: {m: (v.tolist() if isinstance(v, np.ndarray) else v) for m, v in r.items()}
               for k, r in results.items()},
    }
    args.model_out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, args.model_out)
    print(f"\nModèle sauvegardé : {args.model_out}  (features : {', '.join(final_cols)})")
    return {"results": results, "importance": imp, "bundle": bundle}


if __name__ == "__main__":
    main()
