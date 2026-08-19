"""
STEG HelioCast AI - Analyse Exploratoire des Données (EDA).
=============================================================
"""
from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("eda")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MERGE_PATH = PROJECT_ROOT / "data" / "merged" / "GLOBAL" / "merged_all_sites.csv"
EDA_DIR = PROJECT_ROOT / "figures" / "eda"

SITES = ["tozeur_1", "tozeur_2", "meknassi_eppm", "elmourabitine_eni", "feriana_csfb", "feriana_csfc"]
CAPACITY_MW = 10.0

WEATHER_VARS = [
    "shortwave_radiation",
    "direct_normal_irradiance",
    "diffuse_radiation",
    "temperature_2m",
    "cloud_cover",
    "wind_speed_10m",
    "relative_humidity_2m",
    "precipitation",
]

COLORS = plt.cm.tab10(np.linspace(0, 1, 6))


def load_data() -> pd.DataFrame:
    df = pd.read_csv(MERGE_PATH, parse_dates=["timestamp"])
    df = df.sort_values(["site_id", "timestamp"]).reset_index(drop=True)
    logger.info("Charge : %d lignes, %d sites, %s -> %s",
                len(df), df["site_id"].nunique(), df["timestamp"].min(), df["timestamp"].max())
    return df


def save(fig, name: str) -> None:
    EDA_DIR.mkdir(parents=True, exist_ok=True)
    path = EDA_DIR / name
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logger.info("Genere : %s", path.name)


def plot_series(df: pd.DataFrame) -> None:
    fig, axes = plt.subplots(3, 2, figsize=(16, 10), sharex=True)
    for ax, (site, color) in zip(axes.flat, zip(SITES, COLORS)):
        s = df[df["site_id"] == site]
        ax.plot(s["timestamp"], s["production_mw"], lw=0.4, color=color, alpha=0.8)
        ax.set_title(site, fontsize=11)
        ax.set_ylabel("MW")
        ax.grid(alpha=0.3)
        ax.set_ylim(0, CAPACITY_MW + 1)
    fig.suptitle("Production horaire par site (MW)", fontsize=14)
    fig.tight_layout()
    save(fig, "01_series_production_par_site.png")


def plot_daily_profile(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(12, 6))
    for site, color in zip(SITES, COLORS):
        s = df[df["site_id"] == site].groupby("hour")["production_mw"].mean()
        ax.plot(s.index, s.values, marker="o", ms=3, lw=1.5, color=color, label=site)
    ax.set_xlabel("Heure locale (Africa/Tunis)")
    ax.set_ylabel("Production moyenne (MW)")
    ax.set_title("Profil journalier moyen par site")
    ax.grid(alpha=0.3)
    ax.legend(ncol=3, fontsize=9)
    fig.tight_layout()
    save(fig, "02_profil_journalier_moyen.png")


def plot_monthly_profile(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(12, 6))
    for site, color in zip(SITES, COLORS):
        s = df[df["site_id"] == site].groupby("month")["production_mw"].mean()
        ax.plot(s.index, s.values, marker="o", ms=4, lw=1.5, color=color, label=site)
    ax.set_xticks(range(1, 13))
    ax.set_xlabel("Mois")
    ax.set_ylabel("Production moyenne (MW)")
    ax.set_title("Saisonnalite mensuelle par site")
    ax.grid(alpha=0.3)
    ax.legend(ncol=3, fontsize=9)
    fig.tight_layout()
    save(fig, "03_saisonnalite_mensuelle.png")


def plot_hour_month_heatmap(df: pd.DataFrame) -> None:
    pivot = df.pivot_table(index="hour", columns="month", values="production_mw", aggfunc="mean")
    fig, ax = plt.subplots(figsize=(12, 6))
    im = ax.imshow(pivot.values, aspect="auto", cmap="YlOrRd", origin="lower")
    ax.set_xticks(range(12))
    ax.set_xticklabels([f"M{m}" for m in range(1, 13)])
    ax.set_yticks(range(0, 24, 2))
    ax.set_xlabel("Mois")
    ax.set_ylabel("Heure")
    ax.set_title("Production moyenne (MW) : heure x mois — tous sites")
    fig.colorbar(im, ax=ax, label="MW")
    fig.tight_layout()
    save(fig, "04_heatmap_heure_mois.png")


def plot_correlation(df: pd.DataFrame) -> None:
    cols = ["production_mw", *WEATHER_VARS]
    corr = df[cols].corr()
    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(corr.values, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(cols)))
    ax.set_yticks(range(len(cols)))
    ax.set_xticklabels(cols, rotation=45, ha="right")
    ax.set_yticklabels(cols)
    for i in range(len(cols)):
        for j in range(len(cols)):
            ax.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center", fontsize=8)
    ax.set_title("Correlation meteo <-> production")
    fig.colorbar(im, ax=ax, label="r")
    fig.tight_layout()
    save(fig, "05_correlation_meteo_production.png")


def plot_scatter(df: pd.DataFrame, var: str = "shortwave_radiation") -> None:
    day = df[df["is_day"] == 1]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.scatter(day[var], day["production_mw"], s=3, alpha=0.15, color="#f28c28")
    ax.set_xlabel(var)
    ax.set_ylabel("Production (MW)")
    ax.set_title(f"Relation {var} <-> production (jours uniquement)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    save(fig, f"06_scatter_{var}.png")


def plot_distribution(df: pd.DataFrame) -> None:
    day = df[df["is_day"] == 1]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(day["production_mw"], bins=60, color="#0f3d5c", alpha=0.9)
    ax.set_xlabel("Production (MW)")
    ax.set_ylabel("Nombre d'heures")
    ax.set_title("Distribution de la production (jours uniquement)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    save(fig, "07_distribution_production.png")


def plot_capacity_factor(df: pd.DataFrame) -> None:
    monthly = df.copy()
    monthly["ym"] = monthly["timestamp"].dt.to_period("M").astype(str)
    pivot = monthly.pivot_table(index="ym", columns="site_id", values="capacity_factor", aggfunc="mean")
    fig, ax = plt.subplots(figsize=(14, 6))
    pivot.plot(ax=ax, lw=1.2)
    ax.set_xlabel("Mois")
    ax.set_ylabel("Capacity factor (moyenne)")
    ax.set_title("Capacity factor mensuel par site")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, ncol=3)
    fig.tight_layout()
    save(fig, "08_capacity_factor_mensuel.png")


def plot_week_profile(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(12, 6))
    for site, color in zip(SITES, COLORS):
        s = df[df["site_id"] == site].groupby("day_of_week")["production_mw"].mean()
        ax.plot(s.index, s.values, marker="o", ms=4, lw=1.5, color=color, label=site)
    ax.set_xticks(range(7))
    ax.set_xticklabels(["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"])
    ax.set_xlabel("Jour de la semaine")
    ax.set_ylabel("Production moyenne (MW)")
    ax.set_title("Effet jour de semaine (7 jours de pointe solaire inclus)")
    ax.grid(alpha=0.3)
    ax.legend(ncol=3, fontsize=9)
    fig.tight_layout()
    save(fig, "09_profil_semaine.png")


def main() -> None:
    df = load_data()

    missing = df["production_mw"].isna().sum()
    logger.info("Valeurs manquantes production : %d (%.2f %%)", missing, 100 * missing / len(df))
    neg = (df["production_mw"] < 0).sum()
    logger.info("Valeurs negatives production : %d", neg)
    over = (df["production_mw"] > CAPACITY_MW + 1e-6).sum()
    logger.info("Valeurs > capacite (%g MW) : %d", CAPACITY_MW, over)

    plot_series(df)
    plot_daily_profile(df)
    plot_monthly_profile(df)
    plot_hour_month_heatmap(df)
    plot_correlation(df)
    plot_scatter(df, "shortwave_radiation")
    plot_distribution(df)
    plot_capacity_factor(df)
    plot_week_profile(df)

    logger.info("EDA termine : %d graphiques dans %s", len(list(EDA_DIR.glob("*.png"))), EDA_DIR)


if __name__ == "__main__":
    main()
