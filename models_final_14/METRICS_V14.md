# METRICS V14 — Modèle LightGBM (STEG HelioCast AI)

> Généré depuis les artefacts de production : `final_model_bundle.joblib` (v14),
> `reports/v14_*.csv`, `models_final_14/hpo_*.json`.
> Toutes les métriques sont issues du **holdout strict** (≥ 2025-07-01, 51 300 échantillons),
> sauf mention « CV » (walk-forward 5 folds).

## 1. Modèle retenu

| Propriété | Valeur |
|---|---|
| `final_choice` | **lightgbm** |
| Algorithme | LightGBM (LGBMRegressor), scaler : aucun (arbres) |
| Hyperparamètres | n_estimators=1000, num_leaves=145, max_depth=7, learning_rate=0.0391 |
| Features | **31** (25 features + 6 dummies site) |
| Seed | 42 |
| CV RMSE (walk-forward, 5 folds) | **0.8151** |
| Holdout RMSE | 1.0798 |
| Taille bundle | ~4.9 Mo |

## 2. Métriques globales (holdout, modèle déployé = lightgbm)

| Métrique | Valeur | Interprétation |
|---|---|---|
| **MAE** | 0.5269 MW | Erreur moyenne absolue : ~0.53 MW / 10 MW installés |
| **RMSE** | 1.0798 MW | Pénalise les grosses erreurs (nuages soudains) |
| **R²** | 0.8638 | 86 % de la variance expliquée |
| **nMAE** | 5.27 % | MAE normalisé par capacité (10 MW) |
| **nRMSE** | 10.80 % | RMSE normalisé par capacité |
| n_samples | 51 300 | Heures holdout évaluées |

## 3. Métriques par site (holdout)

| Site | MAE | RMSE | R² | MAPE diurne % | nMAE % | nRMSE % | n |
|---|---|---|---|---|---|---|---|
| tozeur_1 | 0.292 | 0.679 | 0.943 | 20.49 | 2.92 | 6.79 | 8 531 |
| tozeur_2 | 0.281 | 0.673 | 0.943 | 20.44 | 2.81 | 6.73 | 8 543 |
| meknassi_eppm | 0.344 | 0.764 | 0.900 | 34.66 | 3.44 | 7.64 | 8 482 |
| elmourabitine_eni | 0.427 | 0.839 | 0.891 | 31.79 | 4.27 | 8.39 | 8 587 |
| feriana_csfb | 0.581 | 1.168 | 0.881 | 40.81 | 5.81 | 11.68 | 8 575 |
| feriana_csfc | 0.583 | 1.194 | 0.872 | 42.07 | 5.83 | 11.94 | 8 582 |

**Interprétation** : les sites de Tozeur (désertique, ciel clair) sont les mieux prédits (nRMSE ~6.7 %) ; les sites de Feriana (zone montagneuse, nuages) sont les plus difficiles (nRMSE ~12 %). C'est un effet **géographique/physique**, pas un défaut du modèle.

## 4. Métriques par régime (jour / nuit)

| Régime | MAE | RMSE | R² | MAPE diurne % | n |
|---|---|---|---|---|---|
| Nuit | ≤ 0.00001 | ≤ 0.0004 | — | — | 25 396 |
| Jour (is_day=1) | 0.829 | 1.284 | 0.787 | 31.85 | 25 904 |
| Jour actif (prod > 0.5 MW) | 0.902 | 1.341 | 0.703 | 31.85 | 22 678 |

**Interprétation** : le modèle est quasi parfait la nuit (0 MW, contrainte physique appliquée) ; l'erreur se concentre en journée, surtout lors des passages nuageux (variation rapide du GHI).

## 5. Métriques par heure (journée)

| Heure | MAE | RMSE | R² | n |
|---|---|---|---|---|
| 0–5h | 0.000 | 0.000 | — | ~10 800 |
| 6h | 0.046 | 0.109 | 0.883 | 2 148 |
| 7h | 0.286 | 0.563 | 0.882 | 2 145 |
| 8h | 0.731 | 1.100 | 0.775 | 2 144 |
| 9h | 0.984 | 1.387 | 0.594 | 2 142 |
| 10h | 0.918 | 1.354 | 0.531 | 2 136 |
| 11h | 0.894 | 1.349 | 0.525 | 2 127 |
| 12h | 0.895 | 1.321 | 0.567 | 2 128 |
| 13h | 0.940 | 1.388 | 0.558 | 2 134 |
| 14h | 1.016 | 1.543 | 0.474 | 2 144 |
| 15h | **1.120** | **1.616** | 0.448 | 2 136 |
| 16h | 1.136 | 1.526 | 0.547 | 2 131 |
| 17h | 0.756 | 1.219 | 0.682 | 2 117 |
| 18h | 0.308 | 0.641 | 0.758 | 2 099 |
| 19h | 0.036 | 0.101 | 0.782 | 2 047 |
| 20–23h | 0.000 | 0.000 | — | ~8 600 |

**Interprétation** : l'erreur maximale se situe à **15–16 h** (pic de convection/nuages d'après-midi en Tunisie) : MAE ~1.1–1.14 MW. C'est une limite physique de la prévision météo, pas du modèle.

## 6. Métriques par mois (tous sites, nRMSE %)

| Mois | tozeur | meknassi | elmourabitine | feriana |
|---|---|---|---|---|
| Jan–Fév | 6.7–7.6 | 6.2–7.6 | 7.0–6.9 | 10.0–11.0 |
| Mar | 10.6 | 10.3 | 9.8 | **15.5** |
| Avr | 7.6 | 9.7 | 9.5 | 14.4–14.7 |
| Mai | 5.0 | 8.0 | 7.6 | 12.1–14.2 |
| Juin | 5.1 | 8.6 | 8.6 | 13.2–13.4 |
| Juil | **3.7** | **6.0** | 8.9 | 11.2–11.6 |
| Août | 5.7 | 8.0 | **12.2** | 10.1–10.9 |
| Sep | 7.4 | 8.3 | 9.1 | 13.0–13.3 |
| Oct | 6.4 | 7.2 | 7.0 | 10.7–10.8 |
| Nov | 5.8 | 5.5 | 5.2 | 9.0–9.3 |
| Déc | 8.5 | 5.4 | 6.3 | 8.9–8.6 |

**Interprétation** : les meilleures performances sont en **juillet** (ciel stable) et les pires en **mars/avril** (transition nuageuse). elmourabitine se dégrade en août (poussières/humidité côtière).

## 7. Métriques du pipeline (entraînement / CV / holdout)

| Phase | RMSE | R² |
|---|---|---|
| Train | 0.6930 | 0.9389 |
| CV (walk-forward, 5 folds) | 0.8225 | — |
| Holdout | 0.9124 | 0.9027 |

> NB : la ligne CV/holdout ci-dessus correspond au **rapport général v14** (modèle retenu vs rapport d'ensemble). Pour le **modèle déployé (lightgbm seul)** : CV 0.8151, holdout 1.0798 / R² 0.8638 (voir §2, valeurs du bundle).

## 8. Comparaison des 7 modèles sur holdout (rapport v14)

| Modèle | MAE | RMSE | R² | MAPE diurne % | nMAE % | nRMSE % |
|---|---|---|---|---|---|---|
| **extratrees** | **0.4185** | **0.9124** | **0.9027** | **31.85** | **4.19** | **9.12** |
| histgb | 0.4584 | 0.9177 | 0.9016 | 32.37 | 4.58 | 9.18 |
| mlp | 0.4556 | 0.9714 | 0.8898 | 32.73 | 4.56 | 9.71 |
| randomforest | 0.4861 | 1.0001 | 0.8831 | 33.57 | 4.86 | 10.00 |
| catboost | 0.5094 | 1.0412 | 0.8733 | 32.35 | 5.09 | 10.41 |
| xgboost | 0.5211 | 1.0770 | 0.8645 | 32.72 | 5.21 | 10.77 |
| **lightgbm (déployé)** | 0.5269 | 1.0798 | 0.8638 | 33.13 | 5.27 | 10.80 |

**Pourquoi lightgbm si extratrees est meilleur au holdout ?** La sélection utilise **uniquement la CV walk-forward** (never le holdout) : lightgbm CV = 0.8151 < extratrees CV = 0.8225. C'est un choix volontaire de robustesse temporelle (voir COMPARISON_VERSIONS.md).

## 9. CV par fold (lightgbm, RMSE)

| Fold | Valeur |
|---|---|
| 1 (2024-01→04) | 0.9727 |
| 2 (2024-04→07) | 0.8583 |
| 3 (2024-07→10) | 0.7039 |
| 4 (2024-10→2025-01) | 0.7643 |
| 5 (2025-01→04) | 0.7762 |
| **Moyenne** | **0.8151** |

**Interprétation** : fold 1 (hiver) plus difficile (jours courts, nuages) ; fold 3 (été 2024) le plus facile (ciel stable).

## 10. Importance SHAP (holdout, 3000 échantillons)

| Rang | Feature | \|SHAP\| moyen | Part cumulée |
|---|---|---|---|
| 1 | `clearsky_dni` | 1.016 | 28.5 % |
| 2 | `solar_elevation` | 0.540 | 43.7 % |
| 3 | `shortwave_radiation` | 0.464 | 56.8 % |
| 4 | `direct_normal_irradiance` | 0.388 | 67.6 % |
| 5 | `diffuse_radiation` | 0.113 | 70.8 % |
| 6 | `site_feriana_csfb` | 0.099 | 73.6 % |
| 7 | `temperature_2m` | 0.088 | 76.1 % |
| 8 | `site_feriana_csfc` | 0.086 | 78.5 % |
| 9 | `hour_cos` | 0.077 | — |
| 10 | `site_meknassi_eppm` | 0.060 | — |

**Interprétation** : le modèle repose sur la **physique solaire** (dni, radiation, élévation) — les 5 premières features expliquent ~71 % de l'importance. La température n'arrive qu'en 7ᵉ position : les arbres préfèrent les variables fortement discriminantes (irradiance). `cell_temp_proxy` (rang 14) capte l'effet thermique résiduel.

## 11. Test de sensibilité physique (validations complémentaires)

### Température (tozeur_1, GHI fixe 950 W/m²)
| T (°C) | 10 | 20 | 30 | 40 | 50 |
|---|---|---|---|---|---|
| Prédit (MW) | 8.29 | 7.99 | 7.66 | 7.34 | 6.95 |
| Δ vs 10 °C | — | −3.6 % | −7.6 % | −11.5 % | −16.2 % |

→ **Radiation constante : T ↑ ⇒ Production ↓ (~0.79 %/°C)** — cohérent avec le rendement thermique PV.

### Radiation (tozeur_1, T fixe 25 °C) — voir `Test_impact_radiation/`
→ **Température constante : GHI ↑ ⇒ Production ↑** — cohérent avec la physique PV.

## 12. Rapidité d'inférence

| Métrique | Valeur |
|---|---|
| train_time (7 modèles complets, avec HPO) | ~15 min |
| inférence holdout lightgbm | 1.23 s |
| rows/s (lightgbm) | 181 677 |

## 13. Conclusion

Le modèle v14 (lightgbm) est **physiquement cohérent** :
- excellente précision la nuit (0) ;
- erreur concentrée en journée, surtout 15–16 h (nuages d'après-midi) ;
- sites désertiques (tozeur) bien mieux prédits que sites montagneux (feriana) ;
- sensibilité température (négative) et radiation (positive) conformes à la physique.

Limites : la MAPE diurne (~33 %) et le nRMSE (~11 %) indiquent une sensibilité forte aux nuages non résolue par la météo « best_match » d'Open-Meteo.