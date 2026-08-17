from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


# ============================================================
# LOGGER
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CONFIG_FILE = PROJECT_ROOT / "config" / "sites.yaml"

PRODUCTION_HOURLY_DIR = (
    PROJECT_ROOT
    / "data"
    / "production_cleaned"
    / "cleaned_hourly"
)

WEATHER_DIR = (
    PROJECT_ROOT
    / "data"
    / "Open-Meteo"
    / "Historical_Forecast"
)

OUTPUT_DIR = PROJECT_ROOT / "data" / "merged"
OUTPUT_GLOBAL_DIR = OUTPUT_DIR / "GLOBAL"

MATCH_RATE_WARNING = 95.0
MATCH_RATE_ERROR = 90.0


# ============================================================
# ERRORS
# ============================================================

class MergeError(Exception):
    """Erreur du pipeline de fusion météo + production."""


# ============================================================
# YAML
# ============================================================

def load_sites() -> dict:
    """
    Charge la configuration des sites depuis sites.yaml.

    Returns
    -------
    dict
        Dictionnaire {site_id: configuration_site}.
    """

    if not CONFIG_FILE.exists():
        raise MergeError(
            f"Fichier introuvable : {CONFIG_FILE}"
        )

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config or "sites" not in config:
        raise MergeError(
            "sites.yaml vide ou clé 'sites' absente."
        )

    sites = {}

    for site in config["sites"]:
        if "id" not in site:
            raise MergeError(
                "Un site ne possède pas de champ 'id'."
            )

        sites[site["id"]] = site

    if not sites:
        raise MergeError(
            "Aucun site trouvé dans sites.yaml."
        )

    return sites


# ============================================================
# CHARGEMENT PRODUCTION
# ============================================================

def load_production(site_id: str) -> pd.DataFrame:
    """
    Charge la production horaire d'un site.

    Le fichier produit par le pipeline de nettoyage contient :
        timestamp
        site_id
        production_mw
    """

    path = (
        PRODUCTION_HOURLY_DIR
        / f"{site_id}_hourly.csv"
    )

    if not path.exists():
        raise MergeError(
            f"Production horaire introuvable pour "
            f"{site_id} : {path}"
        )

    df = pd.read_csv(
        path,
        parse_dates=["timestamp"],
    )

    required_columns = {
        "timestamp",
        "site_id",
        "production_mw",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise MergeError(
            f"{site_id} : colonnes production manquantes : "
            f"{sorted(missing)}"
        )

    df = df[
        [
            "timestamp",
            "site_id",
            "production_mw",
        ]
    ].copy()

    # Conversion numérique
    df["production_mw"] = pd.to_numeric(
        df["production_mw"],
        errors="coerce",
    )

    # Suppression des lignes invalides
    df = df.dropna(
        subset=[
            "timestamp",
            "production_mw",
        ]
    )

    # Vérification des valeurs négatives
    negative_count = int(
        (df["production_mw"] < 0).sum()
    )

    if negative_count > 0:
        logger.warning(
            "%s : %d productions négatives détectées.",
            site_id,
            negative_count,
        )

        df["production_mw"] = (
            df["production_mw"].clip(lower=0)
        )

    # Doublons
    duplicate_count = int(
        df.duplicated(
            subset=["site_id", "timestamp"]
        ).sum()
    )

    if duplicate_count > 0:
        logger.warning(
            "%s : %d timestamps production dupliqués.",
            site_id,
            duplicate_count,
        )

        df = df.drop_duplicates(
            subset=["site_id", "timestamp"],
            keep="last",
        )

    df = (
        df.sort_values("timestamp")
        .reset_index(drop=True)
    )

    return df


# ============================================================
# CHARGEMENT MÉTÉO
# ============================================================

def load_weather(site_id: str) -> pd.DataFrame:
    """
    Charge les données météo horaires d'un site.
    """

    path = (
        WEATHER_DIR
        / f"{site_id}_weather.csv"
    )

    if not path.exists():
        raise MergeError(
            f"Météo introuvable pour "
            f"{site_id} : {path}"
        )

    df = pd.read_csv(
        path,
        parse_dates=["timestamp"],
    )

    required_columns = {
        "timestamp",
        "site_id",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise MergeError(
            f"{site_id} : colonnes météo manquantes : "
            f"{sorted(missing)}"
        )

    # Doublons météo
    duplicate_count = int(
        df.duplicated(
            subset=["site_id", "timestamp"]
        ).sum()
    )

    if duplicate_count > 0:
        logger.warning(
            "%s : %d timestamps météo dupliqués.",
            site_id,
            duplicate_count,
        )

        df = df.drop_duplicates(
            subset=["site_id", "timestamp"],
            keep="last",
        )

    df = (
        df.sort_values("timestamp")
        .reset_index(drop=True)
    )

    return df


# ============================================================
# CONTRÔLE TIMESTAMP
# ============================================================

def validate_timestamps(
    production: pd.DataFrame,
    weather: pd.DataFrame,
    site_id: str,
) -> None:
    """
    Vérifie que les timestamps production et météo
    sont compatibles.
    """

    if production["timestamp"].dt.tz is not None:
        raise MergeError(
            f"{site_id} : timestamps production timezone-aware."
        )

    if weather["timestamp"].dt.tz is not None:
        raise MergeError(
            f"{site_id} : timestamps météo timezone-aware."
        )

    production_minutes = (
        production["timestamp"]
        .dt.minute
        .unique()
    )

    production_seconds = (
        production["timestamp"]
        .dt.second
        .unique()
    )

    weather_minutes = (
        weather["timestamp"]
        .dt.minute
        .unique()
    )

    weather_seconds = (
        weather["timestamp"]
        .dt.second
        .unique()
    )

    if not (
        len(production_minutes) == 1
        and production_minutes[0] == 0
    ):
        logger.warning(
            "%s : production contient des timestamps "
            "qui ne sont pas tous à HH:00.",
            site_id,
        )

    if not (
        len(weather_minutes) == 1
        and weather_minutes[0] == 0
    ):
        logger.warning(
            "%s : météo contient des timestamps "
            "qui ne sont pas tous à HH:00.",
            site_id,
        )

    if not (
        len(production_seconds) == 1
        and production_seconds[0] == 0
    ):
        logger.warning(
            "%s : secondes production non nulles.",
            site_id,
        )

    if not (
        len(weather_seconds) == 1
        and weather_seconds[0] == 0
    ):
        logger.warning(
            "%s : secondes météo non nulles.",
            site_id,
        )


# ============================================================
# FUSION
# ============================================================

def merge_site(
    site_id: str,
) -> tuple[pd.DataFrame, dict]:
    """
    Fusionne production et météo sur :

        site_id + timestamp

    Returns
    -------
    merged : pd.DataFrame
    stats : dict
    """

    production = load_production(site_id)
    weather = load_weather(site_id)

    validate_timestamps(
        production,
        weather,
        site_id,
    )

    n_production = len(production)
    n_weather = len(weather)

    # --------------------------------------------------------
    # Vérification des plages temporelles
    # --------------------------------------------------------

    production_start = production["timestamp"].min()
    production_end = production["timestamp"].max()

    weather_start = weather["timestamp"].min()
    weather_end = weather["timestamp"].max()

    logger.info(
        "%s | Production : %s -> %s",
        site_id,
        production_start,
        production_end,
    )

    logger.info(
        "%s | Météo : %s -> %s",
        site_id,
        weather_start,
        weather_end,
    )

    # --------------------------------------------------------
    # Fusion
    # --------------------------------------------------------

    merged = production.merge(
        weather,
        on=["site_id", "timestamp"],
        how="inner",
        suffixes=("", "_weather"),
        validate="one_to_one",
    )

    n_merged = len(merged)

    unmatched_production = (
        n_production - n_merged
    )

    unmatched_weather = (
        n_weather - n_merged
    )

    match_rate = (
        100.0 * n_merged / n_production
        if n_production > 0
        else 0.0
    )

    stats = {
        "site_id": site_id,
        "n_production": n_production,
        "n_weather": n_weather,
        "n_merged": n_merged,
        "unmatched_production": unmatched_production,
        "unmatched_weather": unmatched_weather,
        "match_rate_%": match_rate,
        "production_start": production_start,
        "production_end": production_end,
        "weather_start": weather_start,
        "weather_end": weather_end,
    }

    # --------------------------------------------------------
    # Contrôle résultat
    # --------------------------------------------------------

    if merged.empty:
        raise MergeError(
            f"{site_id} : aucune correspondance entre "
            "production et météo. "
            "Vérifier timestamp et timezone."
        )

    if match_rate < MATCH_RATE_ERROR:
        raise MergeError(
            f"{site_id} : taux de matching trop faible : "
            f"{match_rate:.2f}% "
            f"(< {MATCH_RATE_ERROR}%)."
        )

    if match_rate < MATCH_RATE_WARNING:
        logger.warning(
            "%s : taux de matching faible : %.2f%%",
            site_id,
            match_rate,
        )

    return merged, stats


# ============================================================
# TIME FEATURES
# ============================================================

def add_time_features(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Ajoute les variables temporelles et cycliques.
    """

    df = df.copy()

    df["hour"] = (
        df["timestamp"].dt.hour
    )

    df["day_of_week"] = (
        df["timestamp"].dt.dayofweek
    )

    df["month"] = (
        df["timestamp"].dt.month
    )

    df["day_of_year"] = (
        df["timestamp"].dt.dayofyear
    )

    # --------------------------------------------------------
    # Encodage cyclique de l'heure
    # --------------------------------------------------------

    df["hour_sin"] = np.sin(
        2 * np.pi * df["hour"] / 24
    )

    df["hour_cos"] = np.cos(
        2 * np.pi * df["hour"] / 24
    )

    # --------------------------------------------------------
    # Encodage cyclique du mois
    # --------------------------------------------------------

    df["month_sin"] = np.sin(
        2 * np.pi * df["month"] / 12
    )

    df["month_cos"] = np.cos(
        2 * np.pi * df["month"] / 12
    )

    return df


# ============================================================
# CAPACITY FACTOR
# ============================================================

def add_capacity_factor(
    df: pd.DataFrame,
    installed_capacity_mwp: float,
    site_id: str,
) -> pd.DataFrame:
    """
    Calcule le capacity factor :

        production_mw / installed_capacity_mwp
    """

    if installed_capacity_mwp <= 0:
        raise MergeError(
            f"{site_id} : capacité installée invalide : "
            f"{installed_capacity_mwp}"
        )

    df = df.copy()

    df["capacity_factor"] = (
        df["production_mw"]
        / installed_capacity_mwp
    )

    # --------------------------------------------------------
    # Contrôle physique
    # --------------------------------------------------------

    negative_cf = int(
        (df["capacity_factor"] < 0).sum()
    )

    above_110 = int(
        (df["capacity_factor"] > 1.10).sum()
    )

    if negative_cf > 0:
        logger.warning(
            "%s : %d capacity_factor négatifs.",
            site_id,
            negative_cf,
        )

    if above_110 > 0:
        logger.warning(
            "%s : %d capacity_factor > 1.10.",
            site_id,
            above_110,
        )

    return df


# ============================================================
# FINAL COLUMN ORDER
# ============================================================

FINAL_COLUMN_ORDER = [
    "timestamp",
    "production_mw",
    "site_id",
    "timezone",

    # Radiation
    "shortwave_radiation",
    "direct_normal_irradiance",
    "direct_radiation",
    "diffuse_radiation",

    # Weather
    "temperature_2m",
    "wind_speed_10m",

    # Clouds
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",

    # Atmosphere
    "relative_humidity_2m",
    "visibility",
    "precipitation",

    # Day / night
    "is_day",

    # Time features
    "hour",
    "day_of_week",
    "month",
    "day_of_year",

    # Cyclic features
    "hour_sin",
    "hour_cos",
    "month_sin",
    "month_cos",

    # Target-related feature
    "capacity_factor",
]


# ============================================================
# REORDER COLUMNS
# ============================================================

def reorder_columns(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Réorganise les colonnes selon un ordre stable.
    """

    missing = [
        column
        for column in FINAL_COLUMN_ORDER
        if column not in df.columns
    ]

    if missing:
        logger.warning(
            "Colonnes attendues manquantes : %s",
            missing,
        )

    ordered = [
        column
        for column in FINAL_COLUMN_ORDER
        if column in df.columns
    ]

    extra = [
        column
        for column in df.columns
        if column not in ordered
    ]

    return df[
        ordered + extra
    ]


# ============================================================
# QUALITY CHECK FINAL
# ============================================================

def validate_merged_dataset(
    df: pd.DataFrame,
    site_id: str,
) -> None:
    """
    Contrôles finaux du dataset fusionné.
    """

    if df.empty:
        raise MergeError(
            f"{site_id} : dataset fusionné vide."
        )

    # --------------------------------------------------------
    # Doublons
    # --------------------------------------------------------

    duplicates = int(
        df.duplicated(
            subset=[
                "site_id",
                "timestamp",
            ]
        ).sum()
    )

    if duplicates > 0:
        raise MergeError(
            f"{site_id} : {duplicates} doublons "
            "site_id + timestamp."
        )

    # --------------------------------------------------------
    # Production manquante
    # --------------------------------------------------------

    missing_production = int(
        df["production_mw"]
        .isna()
        .sum()
    )

    if missing_production > 0:
        raise MergeError(
            f"{site_id} : {missing_production} "
            "productions manquantes."
        )

    # --------------------------------------------------------
    # Capacity factor
    # --------------------------------------------------------

    missing_cf = int(
        df["capacity_factor"]
        .isna()
        .sum()
    )

    if missing_cf > 0:
        raise MergeError(
            f"{site_id} : {missing_cf} "
            "capacity_factor manquants."
        )

    logger.info(
        "%s : contrôle final OK | %d lignes",
        site_id,
        len(df),
    )


# ============================================================
# SAVE SITE
# ============================================================

def save_merged(
    df: pd.DataFrame,
    site_id: str,
) -> Path:
    """
    Sauvegarde le dataset fusionné d'un site.
    """

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = (
        OUTPUT_DIR
        / f"{site_id}_merged.csv"
    )

    df.to_csv(
        output_file,
        index=False,
        encoding="utf-8",
    )

    logger.info(
        "Sauvegardé : %s | %d lignes",
        output_file,
        len(df),
    )

    return output_file


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    logger.info(
        "==================================="
    )
    logger.info(
        "STEG HelioCast AI"
    )
    logger.info(
        "Fusion météo + production"
    )
    logger.info(
        "==================================="
    )

    sites = load_sites()

    all_merged = []
    all_stats = []

    # --------------------------------------------------------
    # Traitement site par site
    # --------------------------------------------------------

    for site_id, site in sites.items():

        logger.info(
            "-----------------------------------"
        )

        logger.info(
            "Traitement du site : %s",
            site_id,
        )

        try:

            # 1. Merge production + météo
            merged, stats = merge_site(
                site_id
            )

            # 2. Time features
            merged = add_time_features(
                merged
            )

            # 3. Capacity factor
            installed_capacity = site.get(
                "installed_capacity_mwp"
            )

            if installed_capacity is None:
                raise MergeError(
                    f"{site_id} : "
                    "installed_capacity_mwp absente."
                )

            merged = add_capacity_factor(
                merged,
                float(installed_capacity),
                site_id,
            )

            # 4. Colonnes finales
            merged = reorder_columns(
                merged
            )

            # 5. QA final
            validate_merged_dataset(
                merged,
                site_id,
            )

            # 6. Sauvegarde site
            save_merged(
                merged,
                site_id,
            )

            # 7. Dataset global
            all_merged.append(
                merged
            )

            all_stats.append(
                stats
            )

            logger.info(
                "%s : %d/%d lignes appariées "
                "(%.2f%%)",
                site_id,
                stats["n_merged"],
                stats["n_production"],
                stats["match_rate_%"],
            )

        except MergeError as error:

            logger.error(
                "%s : %s",
                site_id,
                error,
            )

    # ========================================================
    # DATASET GLOBAL
    # ========================================================

    if not all_merged:

        raise MergeError(
            "Aucun site n'a pu être fusionné."
        )

    global_df = pd.concat(
        all_merged,
        ignore_index=True,
    )

    global_df = (
        global_df
        .sort_values(
            [
                "site_id",
                "timestamp",
            ]
        )
        .reset_index(drop=True)
    )

    OUTPUT_GLOBAL_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    global_file = (
        OUTPUT_GLOBAL_DIR
        / "merged_all_sites.csv"
    )

    global_df.to_csv(
        global_file,
        index=False,
        encoding="utf-8",
    )

    logger.info(
        "========================================"
    )

    logger.info(
        "Dataset global : %s",
        global_file,
    )

    logger.info(
        "Nombre total de lignes : %d",
        len(global_df),
    )

    logger.info(
        "Nombre de sites : %d",
        global_df["site_id"].nunique(),
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    logger.info(
        "========== MERGE SUMMARY =========="
    )

    for stats in all_stats:

        logger.info(
            "%s | Production=%d | Météo=%d | "
            "Merged=%d | Match=%.2f%% | "
            "Prod non appariée=%d | "
            "Météo non appariée=%d",
            stats["site_id"],
            stats["n_production"],
            stats["n_weather"],
            stats["n_merged"],
            stats["match_rate_%"],
            stats["unmatched_production"],
            stats["unmatched_weather"],
        )

    logger.info(
        "==================================="
    )

    logger.info(
        "Fusion terminée avec succès."
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()