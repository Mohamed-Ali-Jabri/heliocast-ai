# COMPARISON DES VERSIONS — STEG HelioCast AI

Ce document compare les versions successives du modèle : `models_final/` (ancienne),
`models_final_13/` (v13) et `models_final_14/` (v14 = production actuelle).

## 1. Vue d'ensemble

| | Ancien (`models_final/`) | v13 (`models_final_13/`) | **v14 (`models_final_14/`)** |
|---|---|---|---|
| `final_choice` | extratrees | extratrees | **lightgbm** |
| Members | extratrees | extratrees | lightgbm |
| Weight | 1.0 | 1.0 | 1.0 |
| Features | 31 | 31 | 31 |
| Taille bundle | ~45 Mo | ~18 Mo | ~4.9 Mo |
| Capacity | `installed_capacity_mw=10.0` (unique) | `capacity_map_mw` (par site) | `capacity_map_mw` (par site) |
| data_hash | absent | absent | **`485e7a3ad340d571c4117f575012cc5f`** |
| training_data_range | 2022-07-13 01:00 → 2026-07-12 01:00 | 2022-07-13 00:00 → 2026-07-12 00:00 | 2022-07-13 00:00 → 2026-07-12 00:00 |
| timestamp_policy | non documenté | timestamps unchanged (Africa/Tunis seul pour pvlib) | idem v13 |
| n_samples holdout | 51 512 | 51 300 | 51 300 |

## 2. Métriques holdout brutes (les nombres « affichés »)

| Métrique | Ancien | v13 | **v14 (lightgbm)** |
|---|---|---|---|
| MAE | 0.3437 | 0.4308 | 0.5269 |
| RMSE | **0.7368** | 0.9161 | 1.0798 |
| R² | **0.9337** | 0.9020 | 0.8638 |
| MAPE diurne % | **23.95** | 32.28 | 33.13 |
| nMAE % | 3.44 | 4.31 | 5.27 |
| nRMSE % | **7.37** | 9.16 | 10.80 |

> **⚠️ ATTENTION — ces chiffres ne sont PAS comparables entre ancien et v13/v14.**

## 3. Pourquoi les métriques ne sont PAS comparables

### a. Données différentes (n_samples)
- Ancien : **51 512** échantillons holdout après shift de +1 h et pipeline legacy.
- v13/v14 : **51 300** (même split chronologique ≥ 2025-07-01, plus 212 lignes écartées par les contrôles v14).

### b. Splits différents
- Ancien : holdout défini autrement (période et mélange sites différents).
- v13/v14 : `HOLDOUT_START = 2025-07-01`, 5 folds walk-forward identiques.

### c. pipeline de nettoyage différent (le point clé)
- Ancien : décale les timestamps de +1 h (`training_data_range` commence à **01:00** au lieu de 00:00) ;
- v13 : corrige le décalage — timestamps **inchangés**, la timezone sert uniquement à pvlib ;
- v14 : conserve cette correction et ajoute le hash des données + contrôles stricts.

Le champion apparent de l'ancien (RMSE 0.7368) a été entraîné sur des données **mal alignées** avec la réalité météo (décalage d'une heure), ce qui rend ses métriques optimistes et **inutilisables en production**.

## 4. Comparaison légitime : v13 vs v14 (mêmes données, mêmes splits)

| Critère | v13 (extratrees) | **v14 (lightgbm)** |
|---|---|---|
| CV RMSE (walk-forward) | 0.8225 | **0.8151** |
| Holdout RMSE | **0.9161** | 1.0798 |
| Holdout R² | **0.9020** | 0.8638 |
| Holdout MAE | **0.4308** | 0.5269 |
| MAPE diurne | 32.28 % | 33.13 % |
| Choix | sur CV (extratrees retenu en v13) | sur CV (lightgbm retenu en v14) |

**Interprétation** : sur les mêmes données/splits, **v13 (extratrees) est meilleur au holdout**, mais **v14 (lightgbm) est meilleur en CV** (le critère de sélection). La décision v14 favorise la robustesse temporelle (moyenne 5 folds) plutôt qu'une seule coupe holdout. Aucune des deux n'est « fausse » : c'est un choix de politique de sélection assumé dans `select_final_model()` (`modeling_v14.py` §25).

> Remarque : dans le holdout **comparé**, l'extratrees de v14 (0.9124) est même meilleur que l'extratrees de v13 (0.9161) — la différence v13/v14 est minime (~0.4 %). Le pipeline v14 (hash, contrôle, catboost fixé) est le plus propre des trois.

## 5. Ce que v14 apporte de vraiment nouveau (indépendant des métriques)

| Apport | Impact |
|---|---|
| `compute_data_hash` (hash `485e7a…`) | Invalide les caches HPO si les données changent → reproductibilité |
| `allow_writing_files=False` pour catboost | Corrige le crash `Can't create train tmp dir` lié au `é` du chemin |
| Branche MLP corrigée dans `build_model` | Le Pipeline(StandardScaler, MLP) se construit correctement |
| `predict_production` tolère les sites manquants (dummies à 0) | L'API/dashboard ne plante plus sur un site seul |
| Sélection finale **sur CV uniquement** | Pas d'overfitting sur le holdout |
| `capacity_map_mw` = 6 × 10 MW | Clip par site dans l'inférence |
| Rapports systématiques `reports/v14_*.csv` | 6 fichiers : holdout, folds, erreurs par site/heure/mois/jour-nuit |

## 6. Synthèse pour la production

| Question | Réponse |
|---|---|
| Quel bundle déployer ? | **`models_final_14/final_model_bundle.joblib`** (lightgbm, v14) |
| Le bundle v13 existe-t-il ? | Oui (`models_final_13/`, extratrees) — utilisable avec `modeling/inference_modelv13.py` → `resultat13.csv` |
| L'ancien bundle (`models_final/`) ? | Conservé pour comparaison, **non déployable** (décalage +1 h, 51 512 lignes non comparables) |
| Quelle interface ? | `modeling/inference.py` (v14) / `modeling/inference_modelv13.py` (v13) |

## 7. Recommandations

1. **Ne pas comparer les nombres de l'ancien au v14** : les mettre dans un tableau (comme ici) avec la mention « non comparable ».
2. Pour un PFE/rapport : présenter **v13 vs v14** (comparaison légitime) + insister sur la **politique de sélection CV**.
3. Si la priorité devient le holdout : re-sélectionner avec `--models-dir` n'est pas nécessaire — l'extratrees v14 existe déjà dans les HPO ; on peut changer `final_choice` sans retrain.
4. Versionner désormais par `data_hash` plutôt que par numéro : le hash est la vraie signature des données.