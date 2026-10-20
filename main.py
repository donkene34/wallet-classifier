"""Phase 6 : API FastAPI.

    uvicorn main:app --reload

    GET /analyze/{address}  -> probabilité qu'une adresse Ethereum soit un bot
    GET /clusters           -> résultat du clustering (PCA 2D + clusters KMeans/DBSCAN)
    GET /health             -> état du service
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import classifier
import collector
import pipeline
from features import FEATURES_PATH, MIN_TX, NotEnoughTransactions, compute_features

DAYS = 90  # fenêtre d'analyse, la même que pour l'entraînement
CLUSTERS_PATH = Path(__file__).parent / "data" / "clusters.json"

app = FastAPI(
    title="wallet-classifier",
    description="Estime si une adresse Ethereum se comporte comme un bot ou un humain (POC).",
    version="1.0.0",
)

# l'interface Next.js (dev) tourne sur le port 3000
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(pipeline.router)

_bundle: dict | None = None
_bundle_mtime: float | None = None


def get_bundle() -> dict:
    """Charge le modèle ; le recharge si le fichier a changé (ex. après un réentraînement depuis l'interface).
    503 clair s'il n'a pas encore été entraîné."""
    global _bundle, _bundle_mtime
    path = classifier.MODEL_PATH
    mtime = path.stat().st_mtime if path.exists() else None
    if _bundle is None or mtime != _bundle_mtime:
        try:
            _bundle = classifier.load_bundle()
        except FileNotFoundError as e:
            _bundle = _bundle_mtime = None
            raise HTTPException(status_code=503, detail=str(e))
        _bundle_mtime = mtime
    return _bundle


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": classifier.MODEL_PATH.exists(),
            "clusters_available": CLUSTERS_PATH.exists()}


@app.get("/analyze/{address}")
def analyze(address: str):
    bundle = get_bundle()
    try:
        txs = collector.get_wallet_transactions(address, days=DAYS)
    except collector.EtherscanError as e:
        raise HTTPException(status_code=502, detail=f"Erreur Etherscan : {e}")
    except ValueError as e:  # adresse invalide
        raise HTTPException(status_code=400, detail=str(e))

    try:
        feats = compute_features(txs, min_tx=MIN_TX)
    except NotEnoughTransactions as e:
        raise HTTPException(
            status_code=422,
            detail=f"Analyse impossible : {e}. Les features comportementales ne sont pas fiables "
                   f"en dessous de {MIN_TX} transactions sur les {DAYS} derniers jours.",
        )

    proba = classifier.predict_proba(bundle, feats)
    return {
        "address": address.lower(),
        "bot_probability": round(proba, 4),
        "label": "bot" if proba >= bundle["threshold"] else "human",
        "top_features": classifier.explain(bundle, feats, top=3),
        "tx_analyzed": int(len(txs)),
    }


@app.get("/clusters")
def clusters():
    if not CLUSTERS_PATH.exists():
        raise HTTPException(status_code=503, detail="clusters.json introuvable. Lance d'abord : python clustering.py")
    return json.loads(CLUSTERS_PATH.read_text(encoding="utf-8"))


@app.get("/examples")
def examples(per_class: int = 4):
    """Wallets du dataset à tester en un clic : répartis du moins actif au plus actif pour chaque classe.
    Attention : le modèle les a vus à l'entraînement, ce ne sont pas des tests indépendants."""
    if not FEATURES_PATH.exists():
        raise HTTPException(status_code=503, detail="features.csv introuvable. Lance d'abord : python features.py")
    df = pd.read_csv(FEATURES_PATH)
    out = []
    for label in ("bot", "human"):
        sub = df[df["label"] == label].sort_values("tx_count").reset_index(drop=True)
        n = min(per_class, len(sub))
        idx = sorted({round(i * (len(sub) - 1) / max(n - 1, 1)) for i in range(n)})
        for i in idx:
            r = sub.iloc[i]
            out.append({"address": r["address"], "dataset_label": label,
                        "category": r.get("category"), "tx_count": int(r["tx_count"])})
    return out


@app.get("/model")
def model_info():
    """Métriques de validation croisée et importance des features du modèle courant."""
    b = get_bundle()
    return {"features": b["features"], "threshold": b["threshold"], "n_train": b["n_train"],
            "n_bots": b["n_bots"], "importance": b["importance"], "cv": b["cv"]}
