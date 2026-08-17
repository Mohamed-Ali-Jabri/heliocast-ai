# """
# STEG HelioCast AI
# =================
 
# Nettoyage des données de production photovoltaïque STEG.
 
# """

# from __future__ import annotations

# import logging
# from dataclasses import dataclass, field
# from datetime import date as date_type
# from datetime import datetime
# from datetime import time as time_type
# from pathlib import Path

# import pandas as pd
# import yaml
# from openpyxl import load_workbook

# # LOGGER 

# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s | %(levelname)s | %(message)s"
# )

# logger = logging.getLogger(__name__)

# #PATHS

# PROJECT_ROOT = Path(__file__).resolve().parents[1]
# CONFIG_FILE = PROJECT_ROOT / "config" / "sites.yaml"
# INPUT_FILE = PROJECT_ROOT / "data" / "PV Production Data" / "PV Production.xlsx"
# OUTPUT_DIR = PROJECT_ROOT / "data" / "production_cleaned"
# CLEAN_DIR = OUTPUT_DIR / "cleaned_minute"
# HOURLY_DIR = OUTPUT_DIR / "cleaned_hourly"

# # MAPPING STEG -> YAML
 
# SITE_CODE_MAPPING = {
#     "TOZ1": "tozeur_1",
#     "TOZ2": "tozeur_2",
#     "Maknassy": "meknassi_eppm",
#     "ENI": "elmourabitine_eni",
#     "CSFB": "feriana_csfb",
#     "CSFC": "feriana_csfc",
# }

# EXCLUDED_CODES = {"Metbasta", "TOZ-IPP", "Mezouna"}

# KNOWN_ERROR_STRINGS = {"", "#N/A", "#VALUE!", "#REF!", "#NAME?", "#DIV/0!"}

# # ERREURS

# class ProductionDataError(Exception):
#     """Erreur du pipeline de nettoyage."""


# @dataclass
# class ProductionLoadReport:
#     site_id_counts: dict[str, int]
#     excluded_columns: int = 0
#     unmapped_columns: list[str] = field(default_factory=list)
#     error_string_count: int = 0
#     none_count: int = 0
#     negative_clipped_count: int = 0
#     out_of_period_count: int = 0
#     total_raw_rows: int = 0



# # Gestion de la configuration YAML
 
 
# def load_sites() -> dict:
#     if not CONFIG_FILE.exists():
#         raise ProductionDataError(f"Fichier introuvable : {CONFIG_FILE}")
 
#     with open(CONFIG_FILE, "r", encoding="utf-8") as f:
#         config = yaml.safe_load(f)
 
#     if not config or "sites" not in config:
#         raise ProductionDataError("sites.yaml vide ou clé 'sites' absente.")
 
#     return {site["id"]: site for site in config["sites"]}

# # sites = load_sites()
# # print(sites)

 
# def validate_sites(sites: dict) -> None:
#     logger.info("Validation de sites.yaml...")
#     mandatory = ["location", "installed_capacity_mwp", "pv_system", "data_period"]
 
#     for site_id, site in sites.items():
#         missing = [f for f in mandatory if f not in site]
#         if missing:
#             raise ProductionDataError(f"{site_id} : champs manquants {missing}")
 
#         period = site["data_period"]
#         for key in ("start_date", "end_date"):
#             if key not in period:
#                 raise ProductionDataError(f"{site_id} : {key} manquant.")
 
#         start = pd.Timestamp(period["start_date"])
#         end = pd.Timestamp(period["end_date"])
#         if start > end:
#             raise ProductionDataError(
#                 f"{site_id} : période invalide ({start.date()} > {end.date()})"
#             )
 
#     logger.info("Configuration YAML valide (%d sites).", len(sites))


# #validate_sites(load_sites())
 
# def build_period_table(sites: dict) -> pd.DataFrame:
#     #Table des bornes de période par site, pour un filtrage vectorisé
#     return pd.DataFrame(
#         [
#             {
#                 "site_id": site_id,
#                 "period_start": pd.Timestamp(site["data_period"]["start_date"]),
#                 "period_end": pd.Timestamp(site["data_period"]["end_date"]),
#             }
#             for site_id, site in sites.items()
#         ]
#     )

# # df_period_table = build_period_table(load_sites())
# # print(df_period_table)


# # DOSSIERS
 
 
# def create_output_directories() -> None:
#     CLEAN_DIR.mkdir(parents=True, exist_ok=True)
#     HOURLY_DIR.mkdir(parents=True, exist_ok=True)

# # LECTURE EXCEL

# def load_header_rows(path: Path):
#     wb = load_workbook(path, read_only=True, data_only=True)
#     ws = wb.active
#     #rows_all = ws.iter_rows(values_only=True)
#     rows = ws.iter_rows(values_only=True, max_row=2)
    

#     try:
#         header = next(rows) # date row 
#         subheader = next(rows) # site code
#     except StopIteration:
#         raise ProductionDataError("Le fichier Excel est invalide.")

#     return header, subheader, wb 
 
# # header, subheader, wb = load_header_rows(INPUT_FILE)
# # print(header) # all dates in the first row
# # print(subheader) # all site codes in the second row
# #print(wb.sheetnames) # sheet name
# # for row in rows_all:
# #     print(row)

# def select_columns(header_row, subheader_row, sites: dict):
#     selected = [] #c olumns to keep: list of tuples (col_idx, date, site_id) ex : 1, date(2022,9,12), "tozeur_1")
#     excluded_columns = 0 # count of columns excluded due to EXCLUDED_CODES
#     unmapped_columns = [] # list of site codes not in SITE_CODE_MAPPING
#     site_counts = {site_id: 0 for site_id in SITE_CODE_MAPPING.values()} # count of selected columns per site_id

#     for col_idx, (date_value, code) in enumerate(
#         zip(header_row[1:], subheader_row[1:]), start=1
#     ):
#         if code is None:
#             continue
#         if code in EXCLUDED_CODES:
#             excluded_columns += 1
#             continue
#         if code not in SITE_CODE_MAPPING:
#             unmapped_columns.append(code)
#             continue
#         if not isinstance(date_value, (datetime, date_type)):
#             logger.warning("Date invalide colonne %d, ignorée.", col_idx)
#             continue

#         site_id = SITE_CODE_MAPPING[code]
#         if site_id not in sites:
#             logger.warning("%s absent du YAML, colonne ignorée.", site_id)
#             continue

#         current_date = date_value.date() if isinstance(date_value, datetime) else date_value
#         selected.append((col_idx, current_date, site_id))
#         site_counts[site_id] += 1

#     report = ProductionLoadReport(
#         site_id_counts=site_counts,
#         excluded_columns=excluded_columns,
#         unmapped_columns=sorted(set(unmapped_columns)),
#     )
#     return selected, report

# # selected_columns, load_report = select_columns(header, subheader, load_sites())
# # print("Colonnes sélectionnées :", selected_columns)
# # print("Rapport de chargement :", load_report)


# def parse_time(value):
#     if isinstance(value, time_type):
#         return value
#     if isinstance(value, datetime):
#         return value.time()
#     return None


# def extract_wide_matrix(ws, selected_columns):

#     col_indices = [c[0] for c in selected_columns] # les id de colonnes selected dans le fichier Excel

#     rows = ws.iter_rows(values_only=True)
#     next(rows)  # header (métadonnées de date) zap
#     next(rows)  # subheader (métadonnées de site) zap

#     times: list[time_type] = []
#     matrix: list[list] = []

#     for row in rows:
#         tod = parse_time(row[0])
#         if tod is None:
#             continue
#         times.append(tod)
#         matrix.append([row[i] for i in col_indices])

#     return times, matrix

# # times , matrix = extract_wide_matrix(wb.active, selected_columns)
# # print(times[:1])
# # print(matrix[:1]) 
# def build_long_dataframe(times, matrix, selected_columns) -> tuple[pd.DataFrame, dict]:
#     """Transforme la matrice large en format long, entièrement vectorisé."""
#     n_cols = len(selected_columns)
#     col_names = [f"c{i}" for i in range(n_cols)]

#     wide = pd.DataFrame(matrix, columns=col_names)
#     wide.insert(0, "time", times)

#     # Table de correspondance colonne -> (date, site_id), utilisée pour
#     # remettre en forme après le melt (évite les pièges du MultiIndex
#     # avec pandas.melt).
#     col_map = pd.DataFrame(
#         {
#             "variable": col_names,
#             "date": [c[1] for c in selected_columns],
#             "site_id": [c[2] for c in selected_columns],
#         }
#     )

#     long_df = wide.melt(id_vars="time", var_name="variable", value_name="raw_value")
#     long_df = long_df.merge(col_map, on="variable", how="left").drop(columns="variable")

#     stats = {"total_raw_cells": len(long_df)}

#     # None / valeurs manquantes
#     stats["none_count"] = int(long_df["raw_value"].isna().sum())

#     # Chaînes d'erreur Excel (et toute chaîne non convertible)
#     is_str = long_df["raw_value"].map(lambda v: isinstance(v, str))
#     stats["error_string_count"] = int(is_str.sum())

#     long_df = long_df.loc[~is_str & long_df["raw_value"].notna()].copy()

#     # Timestamp : date + heure, vectorisé via table de correspondance
#     # des heures uniques (peu nombreuses -> rapide même sur gros volumes)
#     unique_times = long_df["time"].unique()
#     time_deltas = {
#         t: pd.Timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
#         for t in unique_times
#     }
#     long_df["timestamp"] = pd.to_datetime(long_df["date"]) + long_df["time"].map(time_deltas)

#     long_df["production_mw"] = pd.to_numeric(long_df["raw_value"], errors="coerce")
#     long_df = long_df.dropna(subset=["production_mw"])

#     return long_df[["timestamp", "site_id", "production_mw"]], stats


# def filter_by_site_period(df: pd.DataFrame, period_table: pd.DataFrame) -> tuple[pd.DataFrame, int]:
#     """Ne garde que les lignes dans la période de données réelle de chaque site."""
#     before = len(df)
#     merged = df.merge(period_table, on="site_id", how="left")
#     mask = (merged["timestamp"] >= merged["period_start"]) & (
#         merged["timestamp"] <= merged["period_end"]
#     )
#     filtered = merged.loc[mask, ["timestamp", "site_id", "production_mw"]].reset_index(drop=True)
#     return filtered, before - len(filtered)


# # CHARGEMENT COMPLET


# def load_and_clean_production(path: Path, sites: dict) -> tuple[pd.DataFrame, ProductionLoadReport]:
#     path = Path(path)
#     if not path.exists():
#         raise ProductionDataError(f"{path} introuvable")

#     header_row, subheader_row, wb = load_header_rows(path)
#     selected_columns, report = select_columns(header_row, subheader_row, sites)

#     if not selected_columns:
#         wb.close()
#         raise ProductionDataError("Aucune colonne valide.")

#     logger.info("%d colonnes sélectionnées", len(selected_columns))

#     ws = wb.active
#     times, matrix = extract_wide_matrix(ws, selected_columns)
#     wb.close()

#     report.total_raw_rows = len(times)
#     if report.total_raw_rows == 0:
#         raise ProductionDataError("Aucune ligne de données trouvée.")

#     df, stats = build_long_dataframe(times, matrix, selected_columns)
#     report.none_count = stats["none_count"]
#     report.error_string_count = stats["error_string_count"]

#     period_table = build_period_table(sites)
#     df, out_of_period = filter_by_site_period(df, period_table)
#     report.out_of_period_count = out_of_period

#     if df.empty:
#         raise ProductionDataError("Aucune donnée valide après filtrage.")

#     negatives = int((df["production_mw"] < 0).sum())
#     df["production_mw"] = df["production_mw"].clip(lower=0)
#     report.negative_clipped_count = negatives

#     logger.info("Extraction : %d lignes valides", len(df))
#     return df, report


# # AGRÉGATION HORAIRE (MW + kWh)



# def aggregate_to_hourly(df_minute: pd.DataFrame) -> pd.DataFrame:
#     """
#     Agrège les données minute vers un pas horaire.

#     Colonnes retournées :
#         site_id, timestamp,
#         production_mw_mean, production_mw_std, n_valid_minutes,
#         production_kwh  (énergie sur l'heure = puissance moyenne x 1h x 1000)
#     """
#     if df_minute.empty:
#         raise ProductionDataError("DataFrame vide.")

#     df = df_minute.copy()
#     df["hour"] = df["timestamp"].dt.floor("h")

#     hourly = (
#         df.groupby(["site_id", "hour"])["production_mw"]
#         .agg(production_mw_mean="mean", production_mw_std="std", n_valid_minutes="count")
#         .reset_index()
#         .rename(columns={"hour": "timestamp"})
#         .sort_values(["site_id", "timestamp"])
#         .reset_index(drop=True)
#     )

#     hourly["production_mw_std"] = hourly["production_mw_std"].fillna(0)

#     # Énergie horaire en kWh, pour cohérence avec le cahier des charges
#     # (variable cible listée en kWh en section 6.1)
#     hourly["production_kwh"] = hourly["production_mw_mean"] * 1000

#     return hourly


# # ============================================================
# # CONTRÔLE PUISSANCE MAX
# # ============================================================


# def validate_installed_capacity(df: pd.DataFrame, sites: dict) -> None:
#     logger.info("Vérification des puissances installées...")

#     for site_id, group in df.groupby("site_id"):
#         if site_id not in sites:
#             continue

#         installed = sites[site_id]["installed_capacity_mwp"]
#         maximum = group["production_mw"].max()

#         if maximum > installed * 1.10:
#             logger.warning(
#                 "%s : production %.2f MW > capacité %.2f MW", site_id, maximum, installed
#             )
#         else:
#             logger.info("%s : OK (max %.2f MW)", site_id, maximum)


# # ============================================================
# # SAUVEGARDE
# # ============================================================


# def save_clean_dataset(df: pd.DataFrame) -> None:
#     logger.info("Sauvegarde des données nettoyées...")

#     global_file = CLEAN_DIR / "production_all_sites.csv"
#     df.sort_values(["site_id", "timestamp"]).to_csv(global_file, index=False)
#     logger.info("Global : %s", global_file)

#     for site_id, site_df in df.groupby("site_id"):
#         filename = CLEAN_DIR / f"{site_id}.csv"
#         site_df.sort_values("timestamp").to_csv(filename, index=False)
#         logger.info("Site : %s", filename.name)


# def save_hourly_dataset(hourly: pd.DataFrame) -> None:
#     logger.info("Sauvegarde des données horaires...")

#     global_hourly = HOURLY_DIR / "production_hourly_all_sites.csv"
#     hourly.to_csv(global_hourly, index=False)
#     logger.info("Global horaire : %s", global_hourly)

#     for site_id, group in hourly.groupby("site_id"):
#         output = HOURLY_DIR / f"{site_id}_hourly.csv"
#         group.to_csv(output, index=False)
#         logger.info("Horaire : %s", output.name)


# # ============================================================
# # RAPPORT
# # ============================================================


# def print_report(report: ProductionLoadReport) -> None:
#     logger.info("")
#     logger.info("========== RAPPORT ==========")
#     logger.info("Lignes Excel (temps) : %d", report.total_raw_rows)
#     logger.info("Valeurs None : %d", report.none_count)
#     logger.info("Erreurs texte : %d", report.error_string_count)
#     logger.info("Hors période site : %d", report.out_of_period_count)
#     logger.info("Valeurs négatives clippées : %d", report.negative_clipped_count)
#     logger.info("Colonnes exclues : %d", report.excluded_columns)
#     logger.info("Colonnes inconnues : %s", report.unmapped_columns)
#     logger.info("")

#     for site, count in report.site_id_counts.items():
#         logger.info("%s : %d colonnes", site, count)

#     logger.info("=============================")


# # ============================================================
# # MAIN
# # ============================================================


# def main() -> None:
#     logger.info("===================================")
#     logger.info("STEG HelioCast AI")
#     logger.info("Nettoyage des données de production")
#     logger.info("===================================")

#     sites = load_sites()
#     validate_sites(sites)
#     create_output_directories()

#     df, report = load_and_clean_production(INPUT_FILE, sites)
#     validate_installed_capacity(df, sites)
#     save_clean_dataset(df)

#     hourly = aggregate_to_hourly(df)
#     save_hourly_dataset(hourly)

#     print_report(report)

#     logger.info("")
#     logger.info("Nettoyage terminé avec succès.")
#     logger.info("Production minute  : %d lignes", len(df))
#     logger.info("Production horaire : %d lignes", len(hourly))


# if __name__ == "__main__":
#     main()

"""
STEG HelioCast AI
=================
 
Nettoyage des données de production photovoltaïque STEG.
 
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime
from datetime import time as time_type
from pathlib import Path

import pandas as pd
import yaml
from openpyxl import load_workbook

# LOGGER 

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger(__name__)

#PATHS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = PROJECT_ROOT / "config" / "sites.yaml"
INPUT_FILE = PROJECT_ROOT / "data" / "PV Production Data" / "PV Production.xlsx"
OUTPUT_DIR = PROJECT_ROOT / "data" / "production_cleaned"
CLEAN_DIR = OUTPUT_DIR / "cleaned_minute"
HOURLY_DIR = OUTPUT_DIR / "cleaned_hourly"

# MAPPING STEG -> YAML
 
SITE_CODE_MAPPING = {
    "TOZ1": "tozeur_1",
    "TOZ2": "tozeur_2",
    "Maknassy": "meknassi_eppm",
    "ENI": "elmourabitine_eni",
    "CSFB": "feriana_csfb",
    "CSFC": "feriana_csfc",
}

EXCLUDED_CODES = {"Metbasta", "TOZ-IPP", "Mezouna"} 

KNOWN_ERROR_STRINGS = {"", "#N/A", "#VALUE!", "#REF!", "#NAME?", "#DIV/0!"}

# ERREURS

class ProductionDataError(Exception):
    """Erreur du pipeline de nettoyage."""


@dataclass
class ProductionLoadReport:
    site_id_counts: dict[str, int]
    excluded_columns: int = 0
    unmapped_columns: list[str] = field(default_factory=list)
    error_string_count: int = 0
    none_count: int = 0
    negative_clipped_count: int = 0
    out_of_period_count: int = 0
    total_raw_rows: int = 0



# Gestion de la configuration YAML
 

def load_sites() -> dict:
    if not CONFIG_FILE.exists():
        raise ProductionDataError(f"Fichier introuvable : {CONFIG_FILE}")
 
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
 
    if not config or "sites" not in config:
        raise ProductionDataError("sites.yaml vide ou clé 'sites' absente.")
 
    return {site["id"]: site for site in config["sites"]}

# sites = load_sites()
# print(sites)

 
def validate_sites(sites: dict) -> None:
    logger.info("Validation de sites.yaml...")
    mandatory = ["location", "installed_capacity_mwp", "pv_system", "data_period"]
 
    for site_id, site in sites.items():
        missing = [f for f in mandatory if f not in site]
        if missing:
            raise ProductionDataError(f"{site_id} : champs manquants {missing}")
 
        period = site["data_period"]
        for key in ("start_date", "end_date"):
            if key not in period:
                raise ProductionDataError(f"{site_id} : {key} manquant.")
 
        start = pd.Timestamp(period["start_date"])
        end = pd.Timestamp(period["end_date"])
        if start > end:
            raise ProductionDataError(
                f"{site_id} : période invalide ({start.date()} > {end.date()})"
            )
 
    logger.info("Configuration YAML valide (%d sites).", len(sites))


#validate_sites(load_sites())
 
def build_period_table(sites: dict) -> pd.DataFrame:
    #Table des bornes de période par site, pour un filtrage vectorisé
    return pd.DataFrame(
        [
            {
                "site_id": site_id,
                "period_start": pd.Timestamp(site["data_period"]["start_date"]),
                "period_end": pd.Timestamp(site["data_period"]["end_date"]),
            }
            for site_id, site in sites.items()
        ]
    )

# df_period_table = build_period_table(load_sites())
# print(df_period_table)


# DOSSIERS
 
 
def create_output_directories() -> None:
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    HOURLY_DIR.mkdir(parents=True, exist_ok=True)

# LECTURE EXCEL

def load_header_rows(path: Path):
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    #rows_all = ws.iter_rows(values_only=True)
    rows = ws.iter_rows(values_only=True, max_row=2)
    

    try:
        header = next(rows) # date row 
        subheader = next(rows) # site code
    except StopIteration:
        raise ProductionDataError("Le fichier Excel est invalide.")

    return header, subheader, wb 
 
# header, subheader, wb = load_header_rows(INPUT_FILE)
# print(header) # all dates in the first row
# print(subheader) # all site codes in the second row
#print(wb.sheetnames) # sheet name
# for row in rows_all:
#     print(row)

def select_columns(header_row, subheader_row, sites: dict):
    selected = [] #c olumns to keep: list of tuples (col_idx, date, site_id) ex : 1, date(2022,9,12), "tozeur_1")
    excluded_columns = 0 # count of columns excluded due to EXCLUDED_CODES
    unmapped_columns = [] # list of site codes not in SITE_CODE_MAPPING
    site_counts = {site_id: 0 for site_id in SITE_CODE_MAPPING.values()} # count of selected columns per site_id

    for col_idx, (date_value, code) in enumerate(
        zip(header_row[1:], subheader_row[1:]), start=1
    ):
        if code is None:
            continue
        if code in EXCLUDED_CODES:
            excluded_columns += 1
            continue
        if code not in SITE_CODE_MAPPING:
            unmapped_columns.append(code)
            continue
        if not isinstance(date_value, (datetime, date_type)):
            logger.warning("Date invalide colonne %d, ignorée.", col_idx)
            continue

        site_id = SITE_CODE_MAPPING[code]
        if site_id not in sites:
            logger.warning("%s absent du YAML, colonne ignorée.", site_id)
            continue

        current_date = date_value.date() if isinstance(date_value, datetime) else date_value
        selected.append((col_idx, current_date, site_id))
        site_counts[site_id] += 1

    report = ProductionLoadReport(
        site_id_counts=site_counts,
        excluded_columns=excluded_columns,
        unmapped_columns=sorted(set(unmapped_columns)),
    )
    return selected, report

# selected_columns, load_report = select_columns(header, subheader, load_sites())
# print("Colonnes sélectionnées :", selected_columns)
# print("Rapport de chargement :", load_report)


def parse_time(value):
    if isinstance(value, time_type):
        return value
    if isinstance(value, datetime):
        return value.time()
    return None


def extract_wide_matrix(ws, selected_columns):

    col_indices = [c[0] for c in selected_columns] # les id de colonnes selected dans le fichier Excel

    rows = ws.iter_rows(values_only=True)
    next(rows)  # header (métadonnées de date) zap
    next(rows)  # subheader (métadonnées de site) zap

    times: list[time_type] = []
    matrix: list[list] = []

    for row in rows:
        tod = parse_time(row[0])
        if tod is None:
            continue
        times.append(tod)
        matrix.append([row[i] for i in col_indices])

    return times, matrix

# times , matrix = extract_wide_matrix(wb.active, selected_columns)
# print(times[:1])
# print(matrix[:1]) 
def build_long_dataframe(times, matrix, selected_columns) -> tuple[pd.DataFrame, dict]:
    """Transforme la matrice large en format long, entièrement vectorisé."""
    n_cols = len(selected_columns)
    col_names = [f"c{i}" for i in range(n_cols)]

    wide = pd.DataFrame(matrix, columns=col_names)
    wide.insert(0, "time", times)

    # Table de correspondance colonne -> (date, site_id), utilisée pour
    # remettre en forme après le melt (évite les pièges du MultiIndex
    # avec pandas.melt).
    col_map = pd.DataFrame(
        {
            "variable": col_names,
            "date": [c[1] for c in selected_columns],
            "site_id": [c[2] for c in selected_columns],
        }
    )

    long_df = wide.melt(id_vars="time", var_name="variable", value_name="raw_value")
    long_df = long_df.merge(col_map, on="variable", how="left").drop(columns="variable")

    stats = {"total_raw_cells": len(long_df)}

    # None / valeurs manquantes
    stats["none_count"] = int(long_df["raw_value"].isna().sum())

    # Chaînes d'erreur Excel (et toute chaîne non convertible)
    is_str = long_df["raw_value"].map(lambda v: isinstance(v, str))
    stats["error_string_count"] = int(is_str.sum())

    long_df = long_df.loc[~is_str & long_df["raw_value"].notna()].copy()

    # Timestamp : date + heure, vectorisé via table de correspondance
    # des heures uniques (peu nombreuses -> rapide même sur gros volumes)
    unique_times = long_df["time"].unique()
    time_deltas = {
        t: pd.Timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)
        for t in unique_times
    }
    long_df["timestamp"] = pd.to_datetime(long_df["date"]) + long_df["time"].map(time_deltas)

    long_df["production_mw"] = pd.to_numeric(long_df["raw_value"], errors="coerce")
    long_df = long_df.dropna(subset=["production_mw"])

    return long_df[["timestamp", "site_id", "production_mw"]], stats


def filter_by_site_period(df: pd.DataFrame, period_table: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Ne garde que les lignes dans la période de données réelle de chaque site."""
    before = len(df)
    merged = df.merge(period_table, on="site_id", how="left")
    mask = (merged["timestamp"] >= merged["period_start"]) & (
        merged["timestamp"] <= merged["period_end"]
    )
    filtered = merged.loc[mask, ["timestamp", "site_id", "production_mw"]].reset_index(drop=True)
    return filtered, before - len(filtered)


# CHARGEMENT COMPLET


def load_and_clean_production(path: Path, sites: dict) -> tuple[pd.DataFrame, ProductionLoadReport]:
    path = Path(path)
    if not path.exists():
        raise ProductionDataError(f"{path} introuvable")

    header_row, subheader_row, wb = load_header_rows(path)
    selected_columns, report = select_columns(header_row, subheader_row, sites)

    if not selected_columns:
        wb.close()
        raise ProductionDataError("Aucune colonne valide.")

    logger.info("%d colonnes sélectionnées", len(selected_columns))

    ws = wb.active
    times, matrix = extract_wide_matrix(ws, selected_columns)
    wb.close()

    report.total_raw_rows = len(times)
    if report.total_raw_rows == 0:
        raise ProductionDataError("Aucune ligne de données trouvée.")

    df, stats = build_long_dataframe(times, matrix, selected_columns)
    report.none_count = stats["none_count"]
    report.error_string_count = stats["error_string_count"]

    period_table = build_period_table(sites)
    df, out_of_period = filter_by_site_period(df, period_table)
    report.out_of_period_count = out_of_period

    if df.empty:
        raise ProductionDataError("Aucune donnée valide après filtrage.")

    negatives = int((df["production_mw"] < 0).sum())
    df["production_mw"] = df["production_mw"].clip(lower=0)
    report.negative_clipped_count = negatives

    logger.info("Extraction : %d lignes valides", len(df))
    return df, report


# AGRÉGATION HORAIRE (MW + kWh)
def aggregate_to_hourly(df_minute: pd.DataFrame) -> pd.DataFrame:
    """
    Conversion minute vers horaire.

    Conservation uniquement de la mesure réelle
    enregistrée exactement à HH:00:00.

    Aucun calcul :
    - pas de moyenne
    - pas de maximum
    - pas de dernière valeur
    """

    if df_minute.empty:
        raise ProductionDataError("DataFrame vide.")

    hourly = df_minute[
        (df_minute["timestamp"].dt.minute == 0) &
        (df_minute["timestamp"].dt.second == 0)
    ].copy()

    hourly = (
        hourly[
            [
                "site_id",
                "timestamp",
                "production_mw"
            ]
        ]
        .sort_values(
            [
                "site_id",
                "timestamp"
            ]
        )
        .reset_index(drop=True)
    )

    return hourly
# ============================================================
# CONTRÔLE PUISSANCE MAX
# ============================================================


def validate_installed_capacity(df: pd.DataFrame, sites: dict) -> None:
    logger.info("Vérification des puissances installées...")

    for site_id, group in df.groupby("site_id"):
        if site_id not in sites:
            continue

        installed = sites[site_id]["installed_capacity_mwp"]
        maximum = group["production_mw"].max()

        if maximum > installed * 1.10:
            logger.warning(
                "%s : production %.2f MW > capacité %.2f MW", site_id, maximum, installed
            )
        else:
            logger.info("%s : OK (max %.2f MW)", site_id, maximum)


# ============================================================
# SAUVEGARDE
# ============================================================


def save_clean_dataset(df: pd.DataFrame) -> None:
    logger.info("Sauvegarde des données nettoyées...")

    global_file = CLEAN_DIR / "production_all_sites.csv"
    df.sort_values(["site_id", "timestamp"]).to_csv(global_file, index=False)
    logger.info("Global : %s", global_file)

    for site_id, site_df in df.groupby("site_id"):
        filename = CLEAN_DIR / f"{site_id}.csv"
        site_df.sort_values("timestamp").to_csv(filename, index=False)
        logger.info("Site : %s", filename.name)


def save_hourly_dataset(hourly: pd.DataFrame) -> None:
    logger.info("Sauvegarde des données horaires...")

    hourly = hourly.sort_values(
        [
            "site_id",
            "timestamp"
        ]
    )

    global_hourly = HOURLY_DIR / "production_hourly_all_sites.csv"

    hourly.to_csv(
        global_hourly,
        index=False
    )

    logger.info(
        "Global horaire : %s",
        global_hourly
    )

    for site_id, group in hourly.groupby("site_id"):

        output = HOURLY_DIR / f"{site_id}_hourly.csv"

        group.to_csv(
            output,
            index=False
        )

        logger.info(
            "Horaire : %s",
            output.name
        )


# ============================================================
# RAPPORT
# ============================================================


def print_report(report: ProductionLoadReport) -> None:
    logger.info("")
    logger.info("========== RAPPORT ==========")
    logger.info("Lignes Excel (temps) : %d", report.total_raw_rows)
    logger.info("Valeurs None : %d", report.none_count)
    logger.info("Erreurs texte : %d", report.error_string_count)
    logger.info("Hors période site : %d", report.out_of_period_count)
    logger.info("Valeurs négatives clippées : %d", report.negative_clipped_count)
    logger.info("Colonnes exclues : %d", report.excluded_columns)
    logger.info("Colonnes inconnues : %s", report.unmapped_columns)
    logger.info("")

    for site, count in report.site_id_counts.items():
        logger.info("%s : %d colonnes", site, count)

    logger.info("=============================")


# ============================================================
# MAIN
# ============================================================


def main() -> None:
    logger.info("===================================")
    logger.info("STEG HelioCast AI")
    logger.info("Nettoyage des données de production")
    logger.info("===================================")

    sites = load_sites()
    validate_sites(sites)
    create_output_directories()

    df, report = load_and_clean_production(INPUT_FILE, sites)
    validate_installed_capacity(df, sites)
    save_clean_dataset(df)

    hourly = aggregate_to_hourly(df)
    save_hourly_dataset(hourly)

    print_report(report)

    logger.info("")
    logger.info("Nettoyage terminé avec succès.")
    logger.info("Production minute  : %d lignes", len(df))
    logger.info(
    "Production horaire HH:00 uniquement : %d lignes",
    len(hourly)
)


if __name__ == "__main__":
    main()

