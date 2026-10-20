"""Phase 4 : clustering non supervisé des wallets (sans utiliser les labels).

1. normalisation : log1p sur les features très asymétriques, puis StandardScaler
2. méthode du coude (inertie KMeans pour k=1..8) -> k entre 2 et 3
3. KMeans + DBSCAN
4. PCA 2D pour visualiser : clusters trouvés vs vrais labels (comparés seulement APRÈS coup)

Usage :
    python clustering.py                 # lit data/features.csv, écrit les PNG et le JSON dans data/
    python clustering.py --no-log        # sans log1p (StandardScaler seul)
    python clustering.py --k 3 --eps 1.2 # forcer k et/ou eps
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from features import FEATURE_COLUMNS, FEATURES_PATH

SEED = 42
K_MAX = 8
LOG_FEATURES = ["tx_count", "avg_time_between_tx", "std_time_between_tx", "gas_price_std"]

# --- style des figures (palette validée avec le validateur : labels bleu/orange, clusters violet/aqua/magenta)
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
LABEL_COLORS = {"human": "#2a78d6", "bot": "#eb6834"}
LABEL_NAMES = {"human": "Humain", "bot": "Bot"}
CLUSTER_COLORS = ["#6250d6", "#1baf7a", "#e87ba4"]
CLUSTER_MARKERS = ["o", "s", "^"]  # forme différente par cluster : l'identité ne repose pas sur la couleur seule


# --------------------------------------------------------------------------- #
# Données et calculs
# --------------------------------------------------------------------------- #
def load_features(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in ["address", "label", *FEATURE_COLUMNS] if c not in df.columns]
    if missing:
        raise ValueError(f"Colonnes manquantes dans {path.name} : {missing}")
    if len(df) < 10:
        raise ValueError(f"Seulement {len(df)} wallets dans {path.name} : trop peu pour un clustering.")
    return df


def prepare(df: pd.DataFrame, use_log: bool = True) -> np.ndarray:
    """Matrice normalisée. log1p d'abord : sans lui, un wallet à 20 000 tx écrase tout le reste."""
    X = df[FEATURE_COLUMNS].astype(float).copy()
    if use_log:
        for col in LOG_FEATURES:
            X[col] = np.log1p(X[col])
    return StandardScaler().fit_transform(X)


def elbow_inertias(X: np.ndarray, k_max: int = K_MAX) -> list[float]:
    k_max = min(k_max, len(X) - 1)
    return [KMeans(n_clusters=k, n_init=10, random_state=SEED).fit(X).inertia_ for k in range(1, k_max + 1)]


def elbow_k(inertias: list[float]) -> int:
    """Coude = point le plus éloigné de la droite qui relie le premier et le dernier point."""
    y = np.asarray(inertias, dtype=float)
    if len(y) < 3 or y[0] == y[-1]:
        return 2
    x = np.linspace(0, 1, len(y))
    y = (y - y[-1]) / (y[0] - y[-1])
    return int(np.argmax(np.abs(x + y - 1))) + 1


def run_dbscan(X: np.ndarray, min_samples: int = 4, eps: float | None = None):
    """eps par défaut = 90e percentile de la distance au (min_samples-1)-ième voisin."""
    kdist = NearestNeighbors(n_neighbors=min_samples).fit(X).kneighbors(X)[0][:, -1]
    if eps is None:
        eps = float(np.percentile(kdist, 90))
    return DBSCAN(eps=eps, min_samples=min_samples).fit_predict(X), eps


def evaluate(groups: np.ndarray, labels: np.ndarray) -> dict:
    """Comparaison avec les vrais labels, uniquement pour juger le résultat (jamais pour clusteriser)."""
    tab = pd.crosstab(pd.Series(groups, name="cluster"), pd.Series(labels, name="label"))
    tab = tab.reindex(columns=["human", "bot"], fill_value=0)
    real = tab[tab.index != -1] if (tab.index != -1).any() else tab
    share = real["bot"] / real.sum(axis=1)
    best = share.idxmax()
    return {
        "table": tab,
        "ari": float(adjusted_rand_score(labels, groups)),
        "best_cluster": int(best),
        "precision": float(real.loc[best, "bot"] / real.loc[best].sum()),
        "recall": float(real.loc[best, "bot"] / max(tab["bot"].sum(), 1)),
    }


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
def _style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.grid(True, color=GRID, linewidth=1, linestyle="-")
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)


def _scatter(ax, coords, mask, color, marker, label):
    if mask.any():
        ax.scatter(coords[mask, 0], coords[mask, 1], s=70, c=color, marker=marker,
                   edgecolors=SURFACE, linewidths=1.2, zorder=3, label=label)


def _panel_clusters(ax, coords, groups, title):
    ids = [g for g in sorted(set(groups)) if g != -1]
    for rank, g in enumerate(ids):
        mask = groups == g
        if rank < len(CLUSTER_COLORS):
            color, marker, name = CLUSTER_COLORS[rank], CLUSTER_MARKERS[rank], f"Cluster {g}"
        else:
            color, marker, name = MUTED, "D", f"Cluster {g}"
        _scatter(ax, coords, mask, color, marker, f"{name} (n = {mask.sum()})")
    noise = groups == -1
    if noise.any():
        ax.scatter(coords[noise, 0], coords[noise, 1], s=55, c=MUTED, marker="x", linewidths=1.6,
                   zorder=3, label=f"Bruit (n = {noise.sum()})")
    ax.set_title(title, loc="left", fontsize=11, color=INK, pad=10)


def plot_clusters(df, coords, var, km_groups, db_groups, k, eps, path: Path):
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 5.2), sharex=True, sharey=True, facecolor=SURFACE)
    _panel_clusters(axes[0], coords, km_groups, f"KMeans, k = {k} — sans les labels")
    _panel_clusters(axes[1], coords, db_groups, f"DBSCAN, eps = {eps:.2f} — sans les labels")

    labels = df["label"].to_numpy()
    for name in ("human", "bot"):
        mask = labels == name
        _scatter(axes[2], coords, mask, LABEL_COLORS[name], "o", f"{LABEL_NAMES[name]} (n = {mask.sum()})")
    axes[2].set_title("Vrais labels — pour comparer", loc="left", fontsize=11, color=INK, pad=10)

    top = int(np.argmax(df["tx_count"].to_numpy()))  # un seul repère : le wallet au plus gros volume
    for ax in axes:
        _style(ax)
        ax.annotate(f"{int(df['tx_count'].iloc[top]):,} tx".replace(",", " "), coords[top], xytext=(10, 8),
                    textcoords="offset points", ha="left", fontsize=8.5, color=INK2)
        ax.legend(frameon=False, fontsize=9, labelcolor=INK2, loc="best", handletextpad=0.4)
        ax.set_xlabel(f"PC1 ({var[0]:.0%} de la variance)", fontsize=9.5, color=INK2)
    axes[0].set_ylabel(f"PC2 ({var[1]:.0%} de la variance)", fontsize=9.5, color=INK2)

    fig.suptitle("Clustering non supervisé des wallets (projection PCA 2D)", x=0.01, ha="left",
                 fontsize=13.5, color=INK, y=0.99)
    fig.text(0.01, 0.015, f"{len(df)} wallets, {len(FEATURE_COLUMNS)} features. La PCA ne sert qu'à l'affichage ; "
             "les clusters sont calculés sur toutes les features normalisées.", fontsize=8.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def plot_elbow(inertias, k_chosen, path: Path):
    ks = np.arange(1, len(inertias) + 1)
    fig, ax = plt.subplots(figsize=(6.4, 4.3), facecolor=SURFACE)
    _style(ax)
    ax.plot(ks, inertias, color=LABEL_COLORS["human"], linewidth=2, solid_capstyle="round", zorder=2)
    ax.scatter(ks, inertias, s=64, c=LABEL_COLORS["human"], edgecolors=SURFACE, linewidths=1.2, zorder=3)
    i = k_chosen - 1
    ax.scatter([k_chosen], [inertias[i]], s=150, c=LABEL_COLORS["human"], edgecolors=SURFACE, linewidths=1.5, zorder=4)
    ax.annotate(f"k = {k_chosen} retenu", (k_chosen, inertias[i]), xytext=(12, 10), textcoords="offset points",
                fontsize=9.5, color=INK)
    ax.set_xticks(ks)
    ax.set_xlabel("Nombre de clusters k", fontsize=9.5, color=INK2)
    ax.set_ylabel("Inertie (somme des carrés intra-cluster)", fontsize=9.5, color=INK2)
    ax.set_title("Méthode du coude (KMeans)", loc="left", fontsize=12, color=INK, pad=10)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Programme principal
# --------------------------------------------------------------------------- #
def _print_eval(name: str, ev: dict) -> None:
    print(f"\n{name} : ARI = {ev['ari']:.3f}")
    print(ev["table"].to_string())
    print(f"  cluster le plus 'bot' : {ev['best_cluster']}  "
          f"(précision {ev['precision']:.0%}, rappel {ev['recall']:.0%} des bots)")


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path, default=FEATURES_PATH)
    ap.add_argument("--out-dir", type=Path, default=FEATURES_PATH.parent)
    ap.add_argument("--no-log", action="store_true", help="StandardScaler seul, sans log1p")
    ap.add_argument("--k", type=int, help="forcer k au lieu du coude")
    ap.add_argument("--eps", type=float, help="forcer eps de DBSCAN")
    ap.add_argument("--min-samples", type=int, default=4)
    args = ap.parse_args(argv)

    df = load_features(args.features)
    X = prepare(df, use_log=not args.no_log)
    print(f"{len(df)} wallets, {len(FEATURE_COLUMNS)} features, log1p {'non' if args.no_log else 'oui'}")

    inertias = elbow_inertias(X)
    elbow = elbow_k(inertias)
    k = args.k or min(max(elbow, 2), 3)
    sil = {kk: float(silhouette_score(X, KMeans(kk, n_init=10, random_state=SEED).fit_predict(X))) for kk in (2, 3)}
    print(f"Coude : inertie k=1..{len(inertias)} = {[round(v, 1) for v in inertias]}")
    print(f"  coude détecté en k = {elbow}, k retenu = {k} ; silhouette k=2 : {sil[2]:.3f}, k=3 : {sil[3]:.3f}")

    km = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit_predict(X)
    db, eps = run_dbscan(X, args.min_samples, args.eps)
    n_db = len(set(db) - {-1})
    print(f"DBSCAN : eps = {eps:.3f}, min_samples = {args.min_samples} -> {n_db} cluster(s), "
          f"{int((db == -1).sum())} point(s) de bruit")

    labels = df["label"].to_numpy()
    ev_km, ev_db = evaluate(km, labels), evaluate(db, labels)
    _print_eval("KMeans vs vrais labels", ev_km)
    _print_eval("DBSCAN vs vrais labels", ev_db)

    pca = PCA(n_components=2, random_state=SEED).fit(X)
    coords, var = pca.transform(X), pca.explained_variance_ratio_

    args.out_dir.mkdir(parents=True, exist_ok=True)
    fig_path, elbow_path, json_path = (args.out_dir / n for n in ("clusters_pca.png", "elbow.png", "clusters.json"))
    plot_clusters(df, coords, var, km, db, k, eps, fig_path)
    plot_elbow(inertias, k, elbow_path)

    payload = {
        "meta": {
            "k": int(k), "eps": float(eps), "min_samples": int(args.min_samples),
            "log1p": not args.no_log, "features": FEATURE_COLUMNS,
            "pca_explained_variance": [float(v) for v in var],
            "ari_kmeans": ev_km["ari"], "ari_dbscan": ev_db["ari"],
        },
        "points": [
            {"address": r.address, "label": r.label, "pc1": float(coords[i, 0]), "pc2": float(coords[i, 1]),
             "kmeans": int(km[i]), "dbscan": int(db[i])}
            for i, r in enumerate(df.itertuples())
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nÉcrit : {fig_path.name}, {elbow_path.name}, {json_path.name} dans {args.out_dir}")
    return {"k": k, "eps": eps, "km": km, "db": db, "ev_km": ev_km, "ev_db": ev_db, "elbow": elbow}


if __name__ == "__main__":
    main()
