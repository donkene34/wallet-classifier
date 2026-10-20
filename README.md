# wallet-classifier

Estime si une adresse Ethereum se comporte comme un **bot** ou comme un **humain**, à partir de son historique on-chain.

> **Preuve de concept (POC).** Le dataset est petit (85 wallets utilisables) et ses labels sont en partie heuristiques. Les chiffres ci-dessous disent ce que le modèle fait sur *ce* dataset, pas sa précision réelle sur Ethereum. Lis la section [Limites](#limites-honnêtes-à-lire-avant-de-faire-confiance-aux-chiffres).

```
adresse ──► Etherscan V2 ──► 8 features ──► XGBoost ──► {bot_probability, label, top_features}
              (tx 90 j)     (pandas)
```

## Structure

```
collector.py        récupération des transactions (Etherscan V2, pagination, cache SQLite)
features.py         8 features comportementales par wallet
clustering.py       KMeans + DBSCAN + PCA 2D (non supervisé)
classifier.py       XGBoost bot vs humain, évaluation, sauvegarde du modèle
main.py             API FastAPI (/analyze/{address}, /clusters, /examples, /model, /health)
pipeline.py         lance collecte / features / clustering / entraînement depuis l'API (avec logs)
frontend/           interface Next.js (Analyser, Clusters, Pipeline)
collect_labels.py   collecte les transactions de tous les wallets de data/labels.csv
build_labels.py     construit les humains (votants Snapshot) dans labels.csv
discover_bots.py    heuristique pour trouver des candidats bots
data/labels.csv     dataset labellisé (adresse, label, catégorie, source, statut)
data/features.csv   features calculées (généré)
data/clusters.json  résultat du clustering (généré)
models/             modèle entraîné (généré)
```

## Installation

Python 3.10+ (testé avec 3.13).

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS : source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # Linux/macOS : cp .env.example .env
```

Puis édite `.env` et mets ta clé gratuite ([etherscan.io/apis](https://etherscan.io/apis)) :

```
ETHERSCAN_API_KEY=ta_cle_ici
```

Le plan gratuit suffit (~3 requêtes/s, géré par le collecteur).

## Utilisation

Dans l'ordre :

```bash
python collector.py 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 90   # test : tx d'un wallet sur 90 jours
python collect_labels.py --all        # collecte tous les wallets de labels.csv (long : plusieurs minutes, reprise via le cache)
python features.py --offline          # calcule data/features.csv depuis le cache
python clustering.py                  # data/clusters_pca.png, elbow.png, clusters.json
python classifier.py                  # évalue puis écrit models/wallet_classifier.pkl
python -m uvicorn main:app --reload   # API sur http://127.0.0.1:8000  (doc interactive : /docs)
```

Sous Windows, `python -m uvicorn` évite l'erreur « uvicorn n'est pas reconnu » (le dossier Scripts de Python n'est pas toujours dans le PATH).

Les données collectées sont mises en cache dans `data/cache_v2.db` (24 h) : relancer une étape ne rappelle pas Etherscan.

### Interface graphique

Une interface Next.js (TypeScript + Tailwind) permet de tout faire avec des boutons. Prérequis : Node 20.9+ (testé avec Node 22).

```powershell
# terminal 1, dans wallet-classifier
python -m uvicorn main:app --reload

# terminal 2, dans wallet-classifier\frontend
npm install
npm run dev
```

Ouvre http://localhost:3000 (l'API est attendue sur http://127.0.0.1:8000 ; autre adresse : variable `NEXT_PUBLIC_API_URL` dans `frontend/.env.local`). Thème sombre par défaut, bascule clair/sombre en haut à droite.

| Page | Ce qu'elle fait |
|---|---|
| **Analyser** | champ d'adresse, boutons d'exemples du dataset (4 bots, 4 humains), jauge de probabilité, features qui ont le plus pesé. Les exemples viennent du jeu d'entraînement : ce n'est pas un test indépendant |
| **Clusters** | nuage de points PCA coloré par vrais labels, KMeans ou DBSCAN, vue tableau, clic sur un point pour l'analyser |
| **Pipeline** | boutons pour lancer la collecte, les features, le clustering, l'entraînement ou « tout sauf collecte », avec logs en direct, annulation, et métriques du modèle actuel |

La collecte demande une confirmation : elle est longue et consomme ton quota Etherscan. Une seule tâche tourne à la fois, et l'API recharge le modèle automatiquement après un entraînement.

**Problèmes fréquents (Windows)**
- `npm install` coupe avec `ECONNRESET`, puis `EBUSY`/`EPERM` : réseau instable et fichiers verrouillés. Ferme VS Code, supprime `node_modules` (`Remove-Item -Recurse -Force node_modules`), puis relance `npm install --no-audit --no-fund --fetch-retries=5 --fetch-retry-mintimeout=20000`. Si ça persiste, déplace le projet hors du Bureau (synchronisation/antivirus), par exemple dans `C:\dev`.
- `'next' n'est pas reconnu` : `npm install` n'est pas allé au bout, relance-le.
- L'interface affiche « API injoignable » : l'API n'est pas lancée sur le port 8000.
- Ne mets pas à jour npm vers une version incompatible avec ton Node : ce n'est pas nécessaire.

### API

```bash
curl http://127.0.0.1:8000/analyze/0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045
```

Réponse :

```json
{
  "address": "0x...",
  "bot_probability": 0.0352,
  "label": "human",
  "top_features": [
    {"feature": "unique_contracts_ratio", "value": 0.45, "contribution": -1.8},
    {"feature": "hour_entropy", "value": 2.7, "contribution": -0.9},
    {"feature": "tx_count", "value": 18.0, "contribution": -0.4}
  ],
  "tx_analyzed": 18
}
```

`contribution` est la contribution SHAP native de XGBoost : positive = pousse vers « bot », négative = vers « humain ». `label` vaut « bot » si `bot_probability >= 0.5`.

| Code | Cas |
|---|---|
| 400 | adresse invalide |
| 422 | moins de **10 transactions** sur les 90 derniers jours : analyse refusée avec un message clair (les features ne sont pas fiables sur si peu de données) |
| 502 | Etherscan injoignable, ou clé API manquante |
| 503 | modèle pas encore entraîné (`python classifier.py`) |

Autres routes (utilisées par l'interface) :

| Route | Rôle |
|---|---|
| `GET /clusters` | paramètres du clustering et, pour chaque wallet du dataset, ses coordonnées PCA et ses clusters KMeans/DBSCAN |
| `GET /examples` | wallets du dataset à tester en un clic, du moins actif au plus actif |
| `GET /model` | métriques de validation croisée et importance des features du modèle courant |
| `GET /health` | indique si le modèle et les clusters sont présents |
| `POST /pipeline/{collect\|features\|clustering\|train\|rebuild}` | lance une étape (409 si une tâche tourne déjà, 400 si `ETHERSCAN_API_KEY` manque pour `collect`) |
| `GET /pipeline/status`, `GET /pipeline/logs?since=N` | état de la tâche et logs (à partir de la ligne N) |
| `POST /pipeline/cancel` | annule la tâche en cours |

L'API n'a pas d'authentification et peut lancer des scripts : elle est prévue pour un usage **local** (CORS limité à `localhost:3000`). Ne l'expose pas sur Internet telle quelle.

## Méthodologie

**1. Collecte.** Transactions *sortantes* des 90 derniers jours via Etherscan V2 (`txlist`, chaîne 1). L'API plafonne à 1 000 lignes par appel : le collecteur pagine par numéro de bloc, dédoublonne par hash et s'arrête à ~20 000 transactions par wallet (garde-fou).

**2. Features (8).**

| Feature | Idée |
|---|---|
| `tx_count` | volume d'activité |
| `avg_time_between_tx`, `std_time_between_tx` | rythme moyen et régularité (secondes) |
| `hour_entropy` | étalement sur les 24 h (UTC, en bits, max ≈ 4,58) : un bot tourne 24 h/24 |
| `gas_price_std` | variabilité du prix du gas (gwei) |
| `unique_contracts_ratio` | contrats distincts appelés / nombre de tx : un bot rappelle souvent le même contrat |
| `round_amount_ratio` | part de montants « ronds » (≤ 4 décimales) parmi les tx avec valeur > 0 |
| `weekend_ratio` | part des tx le week-end (UTC) |

**3. Clustering (non supervisé, sans les labels).** `log1p` sur les 4 features très asymétriques puis normalisation ; coude KMeans (k retenu = 3) ; DBSCAN (`min_samples=4`, `eps` = 90e percentile de la distance au 4e voisin) ; PCA 2D pour l'affichage. Les labels ne servent qu'*après coup* pour juger le résultat.
Résultat : un groupe de bots très actifs ressort nettement (KMeans : cluster de 18 wallets dont 15 bots, 83 % de précision, mais seulement 68 % des bots retrouvés ; ARI ≈ 0,31). Les bots peu actifs (8 sur 22 ont < 150 tx) se confondent avec les humains. Le clustering seul ne suffit donc pas. Sans `log1p` c'est nettement pire (ARI 0,11).

**4. Classifieur.** XGBoost volontairement petit (200 arbres, profondeur 3), classes pondérées (`scale_pos_weight`). Avec 85 lignes, un seul split train/test serait trop bruité : évaluation par **validation croisée 5 plis × 5 répétitions**, plis construits **par groupe de contrat** (le contrat le plus appelé du wallet) pour que des bots d'un même opérateur ne se retrouvent pas à la fois dans le train et dans le test.

| | Accuracy | Précision | Rappel | AUC |
|---|---|---|---|---|
| Toutes les features | 0,92 | 0,84 | 0,87 | 0,94 |
| Sans `unique_contracts_ratio` | 0,86 | 0,76 | 0,68 | 0,86 |

Référence : répondre toujours « humain » donne 74 % d'accuracy. En moyenne, 19 bots sur 22 sont trouvés pour 4 faux positifs sur 63 humains. `unique_contracts_ratio` domine (≈ 37 % de l'importance).

## Limites honnêtes (à lire avant de faire confiance aux chiffres)

1. **Labels partiellement circulaires.** 25 des 26 bots du fichier (21 des 22 bots utilisables) viennent d'une heuristique (`discover_bots.py`) : des wallets (EOA) qui appellent des contrats privés non vérifiés interagissant avec des pools Uniswap V3. Cette définition recoupe directement `unique_contracts_ratio` : le modèle peut en partie apprendre « à retrouver mon heuristique » plutôt que « ce qu'est un bot ». C'est pour ça que la perte de performance sans cette feature est à lire comme une alerte, pas comme une mesure.
2. **Humains = votants de DAO (Snapshot).** Ce sont des gens engagés dans la gouvernance : population très particulière (selection bias). Beaucoup n'ont aucune transaction on-chain (vote gratuit) et sont écartés : **94 wallets sur 179 ont été éliminés** (< 10 tx), il en reste 85 (63 humains, 22 bots). Un humain ordinaire (trader, joueur NFT, utilisateur de DeFi très actif) est sous-représenté, et sera plus souvent pris pour un bot.
3. **Bots non indépendants.** Plusieurs bots appartiennent au même opérateur (même contrat). Les plis par groupe limitent la fuite, mais l'effectif réel est plus petit que 22.
4. **Labels non vérifiés.** `status = a_verifier` pour presque tout le dataset. Quelques cas douteux sont conservés tels quels : 2 « bots » dont le contrat principal est celui d'USDT (usage possible par un humain) et 3 « humains » au comportement très bot-like.
5. **Peu de types de bots.** Surtout des bots on-chain très actifs (arbitrage/MEV). Les bots discrets (faible volume) ou d'autres usages (airdrop farming, wash trading, spam) ne sont pas couverts. ZeroMEV, la source de bots MEV prévue au départ, était indisponible lors de la collecte.
6. **Fenêtre et plafond.** Analyse sur 90 jours, ≤ 20 000 transactions : un très gros bot est tronqué (début de période conservé). Seules les tx sortantes sont analysées ; les heures et jours sont en UTC.
7. **Pas de calibration.** `bot_probability` est la sortie brute du modèle, pas une probabilité calibrée. Ce n'est pas une preuve : c'est un indice de ressemblance avec le dataset d'entraînement.

**Pistes pour aller plus loin :** de vrais labels indépendants (listes publiques de bots, annotations manuelles), des humains plus variés, des features de graphe (contreparties, fonds reçus), une calibration des probabilités.

## Tests rapides

```bash
python -c "import classifier, clustering, main; print('imports ok')"
curl http://127.0.0.1:8000/health
```
