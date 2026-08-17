"""
STEG HelioCast AI - acces MySQL (base `heliocast`, table `forecasts`).
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import pymysql
from pymysql.cursors import DictCursor

from . import config

log = logging.getLogger("heliocast.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasts (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    timestamp     DATETIME NOT NULL,
    site_id       VARCHAR(64) NOT NULL,
    prediction_mw DECIMAL(10, 4) NOT NULL,
    generated_at  DATETIME NOT NULL,
    UNIQUE KEY uq_site_ts_gen (site_id, timestamp, generated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

SITES_STATUS_SCHEMA = ""
ALLOWED_STATUSES = ()


def _connect() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
    )


def ensure_schema() -> None:
    """Cree la base et les tables si absentes."""
    conn = pymysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{config.DB_NAME}` CHARACTER SET utf8mb4")
        conn.select_db(config.DB_NAME)
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
    finally:
        conn.close()


def upsert_forecasts(forecasts: pd.DataFrame, generated_at: datetime | None = None) -> int:
    """Insere les previsions (colonnes timestamp, site_id, production_predite_mw).

    Upsert par (site_id, timestamp, generated_at) : relancer le job a 00:05
    apres un echec ecrase proprement la meme vague.
    """
    generated_at = generated_at or datetime.now().replace(microsecond=0)
    rows = [
        (ts.to_pydatetime(), site, float(pred), generated_at)
        for ts, site, pred in zip(
            forecasts["timestamp"], forecasts["site_id"], forecasts["production_predite_mw"]
        )
    ]
    if not rows:
        return 0

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO forecasts (timestamp, site_id, prediction_mw, generated_at)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE prediction_mw = VALUES(prediction_mw)
                """,
                rows,
            )
        inserted = conn.affected_rows()
    finally:
        conn.close()
    log.info("Upsert: %d lignes ecrites (affected=%d)", len(rows), inserted)
    return len(rows)


def purge_forecasts(keep_generated_at: datetime | None = None) -> int:
    """Supprime les anciennes previsions.

    - keep_generated_at=None : purge TOTALE (toutes les lignes).
    - keep_generated_at=lot  : conserve uniquement ce lot (les autres sont supprimes).
    """
    conn = _connect()
    try:
        with conn.cursor() as cur:
            if keep_generated_at is None:
                cur.execute("DELETE FROM forecasts")
            else:
                cur.execute("DELETE FROM forecasts WHERE generated_at <> %s", (keep_generated_at,))
            deleted = cur.rowcount
    finally:
        conn.close()
    log.info("Purge: %d lignes supprimees (keep=%s)", deleted, keep_generated_at)
    return deleted


def latest_forecast_batch() -> dict | None:
    """Retourne le dernier lot (generated_at max) + ses lignes."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(generated_at) AS g FROM forecasts")
            row = cur.fetchone()
            if not row or row["g"] is None:
                return None
            generated_at = row["g"]
            cur.execute(
                """
                SELECT site_id, timestamp, prediction_mw
                FROM forecasts
                WHERE generated_at = %s
                ORDER BY timestamp, site_id
                """,
                (generated_at,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {"generated_at": generated_at, "rows": rows}


def ping() -> bool:
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception:
        log.exception("Ping MySQL KO")
        return False


def latest_forecast_batch_csv(csv_path) -> dict | None:
    """Fallback : lit un CSV de previsions (colonnes timestamp, site_id,
    production_predite_mw) quand MySQL est indisponible."""
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path)
    required = {"timestamp", "site_id", "production_predite_mw"}
    if not required.issubset(df.columns):
        log.warning("CSV %s : colonnes attendues %s, trouvees %s", csv_path, required, set(df.columns))
        return None
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    mtime = str(datetime.fromtimestamp(csv_path.stat().st_mtime).replace(microsecond=0))
    rows = [
        {"site_id": str(r.site_id), "timestamp": r.timestamp, "prediction_mw": float(r.production_predite_mw)}
        for r in df.itertuples(index=False)
    ]
    if not rows:
        return None
    log.info("Fallback CSV %s : %d lignes (mtime %s)", csv_path, len(rows), mtime)
    return {"generated_at": mtime, "rows": rows}
