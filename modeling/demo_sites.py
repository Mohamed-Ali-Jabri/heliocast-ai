"""
STEG HelioCast AI - Demo réels vs prédits pour tous les sites, un jour donné.
=============================================================================
Affiche (et sauvegarde) un tableau timestamp / site_id / production_reelle_mw /
production_predite_mw pour une date au choix (défaut : 2025-07-01).

Usage :
    python modeling/demo_sites.py                # jour par défaut 2025-07-01
    python modeling/demo_sites.py 2025-03-15     # autre jour
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DATE = "2025-07-01"
OUTPUT_CSV = PROJECT_ROOT / "modeling" / "demo_sites.csv"


def load_pipeline():
    spec = importlib.util.spec_from_file_location(
        "heliocast_inference", PROJECT_ROOT / "modeling" / "inference.py"
    )
    inference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inference)
    return inference.ForecastPipeline(
        str(PROJECT_ROOT / "models_final_14" / "final_model_bundle.joblib")
    )


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    date_str = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DATE
    date_str = date_str.strip()

    pipe = load_pipeline()
    df = pd.read_csv(PROJECT_ROOT / "data" / "final_data" / "steg_pv_features.csv",
                     parse_dates=["timestamp"])

    demo = df[df["timestamp"].dt.strftime("%Y-%m-%d") == date_str].copy()
    if len(demo) == 0:
        print(f"Aucune donnée pour la date {date_str}.")
        return

    demo = demo.sort_values(["site_id", "timestamp"]).reset_index(drop=True)
    pred = pipe.predict(demo)

    out = pd.DataFrame({
        "timestamp": demo["timestamp"].values,
        "site_id": demo["site_id"].values,
        "production_reelle_mw": np.round(demo["production_mw"].values, 3),
        "production_predite_mw": np.round(pred["production_predite_mw"].to_numpy(), 3),
    })

    print(f"\n========== REELS vs PREDITS — {date_str} — tous les sites ==========")
    print(out.to_string(index=False))

    OUT = PROJECT_ROOT / "modeling" / f"demo_{date_str}_tous_sites.csv"
    out.to_csv(OUT, index=False)
    mae = np.mean(np.abs(out["production_reelle_mw"] - out["production_predite_mw"]))
    print(f"\nMAE global du jour : {mae:.3f} MW")
    print(f"SAVED : {OUT}")


if __name__ == "__main__":
    main()