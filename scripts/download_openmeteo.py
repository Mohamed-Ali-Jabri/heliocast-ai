from __future__ import annotations
import logging
import time
from pathlib import Path
import pandas as pd
import requests
import yaml 
import json


# CONFIGURATION

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SITES_FILE= PROJECT_ROOT / "config" / "sites.yaml"
OUTPUT_DIR= PROJECT_ROOT / "data" / "Open-Meteo" / "Historical_Forecast"
GLOBAL_FILE = OUTPUT_DIR /"Global" /"weather_all_sites.csv"
QUALITY_DIR = PROJECT_ROOT / "data" / "Historical_Forecast" / "Quality"
API_URL = ("https://historical-forecast-api.open-meteo.com/v1/forecast")



# Variables météo utilisées pour le forecasting photovoltaïque
HOURLY_VARIABLES = [

    # Irradiance solaire (variables les plus importantes)
    "shortwave_radiation",
    "direct_normal_irradiance",
    "direct_radiation",
    "diffuse_radiation",

    # Température et vent
    "temperature_2m",
    "wind_speed_10m",

    # Nuages
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",

    # Atmosphère
    "relative_humidity_2m",
    "visibility",
    "precipitation",

    # Jour / nuit
    "is_day",
]

# Nombre de secondes entre deux requêtes
REQUEST_DELAY = 1

# Si True, le fichier existant sera remplacé
OVERWRITE = False

# LOGGING

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger(__name__)


# LOAD YAML

def load_sites(sites_file: Path,) -> list[dict]:

    if not sites_file.exists():

        raise FileNotFoundError(
            f"Fichier YAML introuvable : {sites_file}"
        )

    with open(sites_file,"r",encoding="utf-8",) as file:

        config = yaml.safe_load(file)

    if not config:
        raise ValueError(
            "Le fichier YAML est vide."
        )

    sites = config.get("sites")

    if not sites:
        raise ValueError(
            "La clé 'sites' est absente ou vide."
        )

    return sites

#sites=load_sites(SITES_FILE)
# logger.info(f"Fichier YAML chargé avec succès : {SITES_FILE}, contenant {len(sites)} sites.")
# print(sites)



# VALIDATE SITE CONFIGURATION

def validate_site(site: dict,) -> None:

    required_fields = ["id","name","location","data_period",]

    for field in required_fields:

        if field not in site:

            raise ValueError(
                f"Champ '{field}' manquant "
                f"pour le site {site.get('id', 'UNKNOWN')}"
            )


    location = site["location"]

    if "latitude" not in location:
        raise ValueError(
            f"Latitude manquante pour {site['id']}"
        )

    if "longitude" not in location:
        raise ValueError(
            f"Longitude manquante pour {site['id']}"
        )

    if "timezone" not in location:
        raise ValueError(
            f"Timezone manquante pour {site['id']}"
        )


    period = site["data_period"]

    if "start_date" not in period:
        raise ValueError(
            f"start_date manquante pour {site['id']}"
        )

    if "end_date" not in period:
        raise ValueError(
            f"end_date manquante pour {site['id']}"
        )


    start = pd.Timestamp(period["start_date"]
    )

    end = pd.Timestamp(period["end_date"]
    )


    if start > end:

        raise ValueError(
            f"Période invalide pour {site['id']} : "
            f"{start.date()} > {end.date()}"
        )



# BUILD API PARAMETERS

def build_api_params(site: dict,) -> dict:

    location = site["location"]

    period = site["data_period"]


    params = {

        "latitude":
            location["latitude"],

        "longitude":
            location["longitude"],

        "hourly":
            ",".join(
                HOURLY_VARIABLES
            ),

        "start_date":
            period["start_date"],

        "end_date":
            period["end_date"],

        "timezone":
            location["timezone"],

        "models":
            "best_match",

    }


    return params

# for site in sites:
#     try: 
#         validate_site(site)
#         logging.info(f"Site {site['id']} validé avec succès.")
    
#     except ValueError as e:
#         logging.error(f"Erreur de validation pour le site {site['id']}: {e}")

#     params = build_api_params(site)
#     logger.info(f"Paramètres API pour {site['id']} : {params}/n")



# DOWNLOAD OPEN-METEO DATA

def download_weather(site: dict,) -> dict:

    site_id = site["id"]

    params = build_api_params(site)


    logger.info(
        "Téléchargement météo : %s | %s -> %s",
        site_id,
        params["start_date"],
        params["end_date"],
    )

    response = requests.get(

        API_URL,
        params=params,
        timeout=300,
    )


    response.raise_for_status() #vérifie si la requête a réussi


    data = response.json()


    if "hourly" not in data:

        raise ValueError(
            f"Réponse Open-Meteo invalide "
            f"pour {site_id}"
        )


    return data

# for site in sites : 
#     downloaded_data = download_weather(site)
#     logger.info(f"Données téléchargées pour le site {site['id']}.")
#     print(downloaded_data)


# JSON -> DATAFRAME

def json_to_dataframe(data: dict,site: dict,) -> pd.DataFrame:

    site_id = site["id"]
    timezone = (site["location"]["timezone"])
    hourly_data = data["hourly"]

    df = pd.DataFrame(hourly_data)

    if df.empty:
        raise ValueError(
            f"Aucune donnée météo pour "
            f"{site_id}"
        )

    # Renommer time
    df = df.rename(

        columns={
            "time": "timestamp"
        }
    )

    # Conversion datetime
    df["timestamp"] = pd.to_datetime(

        df["timestamp"],

        errors="coerce", # Les valeurs invalides sont transformées en NaT
    )

    # Supprimer timestamps invalides
    df = df.dropna(
        subset=["timestamp"]
    )

    # Ajouter site_id
    df["site_id"] = site_id

    # Ajouter timezone
    df["timezone"] = timezone

    # Réorganiser les colonnes
    first_columns = [

        "timestamp",
        "site_id",
        "timezone",

    ]
    # rest of the columns 
    remaining_columns = [
        col for col in df.columns if col not in first_columns
]


    df = df[
        first_columns
        +
        remaining_columns
    ]


    return df


# CLEAN WEATHER DATA

def clean_weather_data(df: pd.DataFrame) -> pd.DataFrame:

    if df.empty:

        return df


    # Trier chronologiquement

    df = df.sort_values("timestamp")


    # Supprimer doublons

    df = df.drop_duplicates(

        subset=[
            "timestamp",
            "site_id",
        ],
        keep="last",

    )


    # Colonnes numériques

    numeric_columns = (

        df.select_dtypes(
            include="number"
        )
        .columns
        .tolist()

    )


    # Conversion numérique

    for column in numeric_columns:

        df[column] = pd.to_numeric(

            df[column],

            errors="coerce",

        )


    # Nettoyage physique

    if "cloud_cover" in df.columns:

        df.loc[

            (df["cloud_cover"] < 0)
            |
            (df["cloud_cover"] > 100),

            "cloud_cover"

        ] = pd.NA


    if "relative_humidity_2m" in df.columns:

        df.loc[

            (
                df["relative_humidity_2m"]
                < 0
            )
            |
            (
                df["relative_humidity_2m"]
                > 100
            ),

            "relative_humidity_2m"

        ] = pd.NA


    if "wind_speed_10m" in df.columns:

        df.loc[

            df["wind_speed_10m"] < 0,

            "wind_speed_10m"

        ] = pd.NA


    if "precipitation" in df.columns:

        df.loc[

            df["precipitation"] < 0,

            "precipitation"

        ] = pd.NA


    if "shortwave_radiation" in df.columns:

        df.loc[

            df["shortwave_radiation"] < 0,

            "shortwave_radiation"

        ] = 0


    if "direct_radiation" in df.columns:

        df.loc[

            df["direct_radiation"] < 0,

            "direct_radiation"

        ] = 0


    if "diffuse_radiation" in df.columns:

        df.loc[

            df["diffuse_radiation"] < 0,

            "diffuse_radiation"

        ] = 0


    if "direct_normal_irradiance" in df.columns:

        df.loc[

            df["direct_normal_irradiance"] < 0,

            "direct_normal_irradiance"

        ] = 0


    # Retour final

    df = df.reset_index(
        drop=True
    )


    return df

def generate_quality_report(
    df_before: pd.DataFrame,
    df_after: pd.DataFrame,
    site_id: str,
) -> dict:

    report = {}

    # Création dossier qualité
    QUALITY_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


    # Informations générales

    report["site_id"] = site_id

    report["initial_rows"] = int(
        len(df_before)
    )

    report["final_rows"] = int(
        len(df_after)
    )

    report["rows_removed"] = int(
        len(df_before)
        -
        len(df_after)
    )


    # Doublons supprimés

    duplicates = (
        df_before
        .duplicated(
            subset=[
                "timestamp",
                "site_id"
            ]
        )
        .sum()
    )

    report["duplicates_removed"] = int(
        duplicates
    )


    # Timestamps invalides

    report["invalid_timestamps"] = int(
        df_before["timestamp"]
        .isna()
        .sum()
    )


    # Valeurs manquantes

    report["missing_values"] = {
        column: int(value)
        for column, value in (
            df_after
            .isna()
            .sum()
            .to_dict()
            .items()
        )
    }


    # Complétude des données

    total_cells = int(
        df_after.shape[0]
        *
        df_after.shape[1]
    )


    missing_cells = int(
        df_after
        .isna()
        .sum()
        .sum()
    )


    if total_cells > 0:

        completeness = (
            1 -
            missing_cells / total_cells
        ) * 100

    else:

        completeness = 0


    report["data_completeness_%"] = round(
        float(completeness),
        2
    )


    # Informations supplémentaires

    report["columns"] = (
        df_after
        .columns
        .tolist()
    )


    if not df_after.empty:

        report["start_date"] = (
            df_after["timestamp"]
            .min()
            .strftime("%Y-%m-%d")
        )

        report["end_date"] = (
            df_after["timestamp"]
            .max()
            .strftime("%Y-%m-%d")
        )

        report["days"] = int(
            df_after["timestamp"]
            .dt.date
            .nunique()
        )

    else:

        report["start_date"] = None
        report["end_date"] = None
        report["days"] = 0



    # Sauvegarde JSON par site

    output_file = (
        QUALITY_DIR
        /
        f"{site_id}_quality_report.json"
    )


    with open(
        output_file,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            report,
            file,
            indent=4,
            ensure_ascii=False,
        )


    logger.info(
        "Quality report sauvegardé : %s",
        output_file,
    )


    return report

    


# SAVE SITE DATA

def save_site_data(df: pd.DataFrame,site_id: str) -> Path:

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
)


    output_file = (
        OUTPUT_DIR / f"{site_id}_weather.csv"
)


    if (output_file.exists() and not OVERWRITE):

        logger.warning(
            "Fichier déjà existant, "
            "sauvegarde ignorée : %s",
            output_file,
)

        return output_file


    df.to_csv(
        output_file,
        index=False,
        encoding="utf-8",
    )


    logger.info(
        "Fichier sauvegardé : %s | %d lignes",
        output_file,
        len(df),
    )

    return output_file


# MAIN


def main():

    logger.info(
        "========== STEG HelioCast AI =========="
    )

    logger.info(
        "Chargement de la configuration..."
    )


    # 1 - Charger les sites depuis YAML

    sites = load_sites(SITES_FILE)

    logger.info(
        "%d sites trouvés dans sites.yaml",
        len(sites),
    )


    all_weather = []
    successful_sites = []
    failed_sites = []
    quality_reports = []


    # Boucle sur les sites

    for site in sites:

        site_id = site["id"]


        existing_file = (
            OUTPUT_DIR /
            f"{site_id}_weather.csv"
        )


        try:

            # Si fichier existe déjà

            if existing_file.exists() and not OVERWRITE:

                logger.info(
                    "Données existantes pour %s, chargement local",
                    site_id,
                )


                df_after = pd.read_csv(
                    existing_file
                )

                df_after["timestamp"] = pd.to_datetime(
                    df_after["timestamp"]
                )


                all_weather.append(
                    df_after
                )


                successful_sites.append(
                    site_id
                )


                continue



            # 2 - Validation site

            validate_site(site)


            start_date = site["data_period"]["start_date"]
            end_date = site["data_period"]["end_date"]


            logger.info(
                "%s : %s -> %s",
                site_id,
                start_date,
                end_date,
            )



            # 3 - Téléchargement Open-Meteo

            raw_data = download_weather(site)



            # 4 - JSON vers DataFrame

            df_before = json_to_dataframe(
                raw_data,
                site,
            )



            # 5 - Nettoyage

            df_after = clean_weather_data(
                df_before
            )



            # 6 - Rapport qualité

            quality_report = generate_quality_report(
                df_before=df_before,
                df_after=df_after,
                site_id=site_id,
            )
            quality_reports.append(
                quality_report
            )

            # 7 - Sauvegarde individuelle
            save_site_data(
                df_after,
                site_id,
            )


            # 8 - Ajouter dataset global

            all_weather.append(
                df_after
            )


            successful_sites.append(
                site_id
            )



        except Exception as error:


            logger.exception(
                "Erreur pour le site %s : %s",
                site_id,
                error,
            )


            failed_sites.append(
                site_id
            )



        # Pause API

        time.sleep(
            REQUEST_DELAY
        )




    # ================================
    # DATASET GLOBAL
    # ================================


    if all_weather:


        weather_all = pd.concat(
            all_weather,
            ignore_index=True,
        )


        weather_all = (
            weather_all
            .sort_values(
                [
                    "site_id",
                    "timestamp",
                ]
            )
            .reset_index(
                drop=True
            )
        )


        GLOBAL_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )


        weather_all.to_csv(
            GLOBAL_FILE,
            index=False,
            encoding="utf-8",
        )


        logger.info(
            "Dataset global sauvegardé : %s",
            GLOBAL_FILE,
        )


        logger.info(
            "Nombre total de lignes : %d",
            len(weather_all),
        )



    # ================================
    # SUMMARY
    # ================================


    logger.info(
        "========================================"
    )


    logger.info(
        "Téléchargement terminé."
    )


    logger.info(
        "Sites réussis : %s",
        successful_sites,
    )


    logger.info(
        "Sites échoués : %s",
        failed_sites,
    )



    # ================================
    # QUALITY SUMMARY
    # ================================


    logger.info(
        "========== QUALITY SUMMARY =========="
    )


    for report in quality_reports:


        logger.info(
            "Site : %s | Initial : %d | Final : %d | Removed : %d | Completeness : %.2f%%",
            report["site_id"],
            report["initial_rows"],
            report["final_rows"],
            report["rows_removed"],
            report["data_completeness_%"],
        )


        logger.info(
            "========================================"
        )



# ENTRY POINT


if __name__ == "__main__":

    main()