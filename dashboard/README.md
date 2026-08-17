# STEG HelioCast — Dashboard opérateur (React + Tailwind + Recharts)

Dashboard professionnel **orienté opérateur** : aucune donnée technique (ML, RMSE, API, base de données). Seule la production solaire prévue est affichée.

## Données

Consomme **uniquement** `GET /forecasts/latest` (backend FastAPI).

## Lancer en développement

1. Démarrer l'API (racine du projet) :
   ```
   python -m uvicorn deploy.app.api:app --host 127.0.0.1 --port 8000
   ```
2. Dans `dashboard/` :
   ```
   npm install
   npm run dev
   ```
3. Ouvrir http://localhost:5173 (proxy Vite → API sur 8000).

## Intégrer au serveur de production

```
npm run build
```
Le dossier `dist/` (fichiers statiques) peut être :
- servi par le backend FastAPI (copier le contenu de `dist/` dans `deploy/app/static/`), ou
- servi par Nginx dans l'architecture Docker.

## Structure

```
src/
├── App.jsx                 # Router + chargement global des données
├── api/client.js           # GET /forecasts/latest (unique source)
├── hooks/useForecasts.js   # état loading/error/data + retry
├── config/sites.js         # constantes métier (6 centrales, capacités)
├── utils/forecastMath.js   # dérivations (MWh/jour, pics, météo dérivée)
├── components/             # Layout, cartes, icônes animées, carte Tunisie
└── pages/                  # Overview, Forecast, Plants, Calendar
```