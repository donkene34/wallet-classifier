# wallet-classifier : interface

Interface Next.js (TypeScript + Tailwind) pour l'API FastAPI du projet.

```powershell
# terminal 1 (dossier wallet-classifier)
python -m uvicorn main:app --reload

# terminal 2 (dossier wallet-classifier\frontend)
npm install
npm run dev
```

Ouvre http://localhost:3000. L'API est attendue sur http://127.0.0.1:8000
(autre adresse : variable `NEXT_PUBLIC_API_URL`, par exemple dans `frontend/.env.local`).

- **Analyser** : champ d'adresse, boutons d'exemples du dataset, jauge de probabilité, features qui ont pesé.
- **Clusters** : nuage de points PCA (vrais labels / KMeans / DBSCAN), vue tableau, clic pour analyser un wallet.
- **Pipeline** : boutons pour collecter, calculer les features, clusteriser, entraîner, avec les logs en direct.
