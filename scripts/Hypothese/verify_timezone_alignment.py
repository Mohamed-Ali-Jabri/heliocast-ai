from pathlib import Path
import pandas as pd
import json



# PATH


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data" / "merged"
QUALITY_FILE = PROJECT_ROOT / "scripts" / "Hypothese" 


if not DATA_DIR.exists():
    raise FileNotFoundError(
        f"Dossier introuvable : {DATA_DIR}"
    )




# CALCUL LAG CORRELATION


def calculate_lag_correlations(
        df,
        production_col="production_mw",
        weather_col="shortwave_radiation",
        max_lag=6
):

    data = df[
        [
            production_col,
            weather_col
        ]
    ].dropna()


    results = []


    for lag in range(-max_lag, max_lag + 1):

        shifted_weather = data[weather_col].shift(lag)


        correlation = (
            data[production_col]
            .corr(shifted_weather)
        )


        results.append(
            {
                "lag": lag,
                "correlation": round(correlation, 3)
            }
        )


    return pd.DataFrame(results)




# VERIFY ALL SITES


def verify_sites():


    files = DATA_DIR.glob("*_merged.csv")


    global_summary = []


    for file in files:


        site_id = file.stem.replace(
            "_merged",
            ""
        )


        print("\n")
        print("=" * 50)
        print(f"SITE : {site_id}")
        print("=" * 50)



        df = pd.read_csv(
            file,
            parse_dates=["timestamp"]
        )


        lag_results = calculate_lag_correlations(
            df
        )


        # Affichage tous les lags

        print(
            lag_results.to_string(index=False)
        )



        # meilleur lag

        best = lag_results.loc[
            lag_results["correlation"].idxmax()
        ]



        # corrélation lag 0

        lag0 = lag_results[
            lag_results["lag"] == 0
        ]["correlation"].values[0]



        global_summary.append(

            {

                "Site": site_id,


                "Corr_lag_-6h":
                    lag_results.iloc[0]["correlation"],

                "Corr_lag_-5h":
                    lag_results.iloc[1]["correlation"],

                "Corr_lag_-4h":
                    lag_results.iloc[2]["correlation"],

                "Corr_lag_-3h":
                    lag_results.iloc[3]["correlation"],

                "Corr_lag_-2h":
                    lag_results.iloc[4]["correlation"],

                "Corr_lag_-1h":
                    lag_results.iloc[5]["correlation"],


                "Corr_lag_0h":
                    lag0,


                "Corr_lag_+1h":
                    lag_results.iloc[7]["correlation"],

                "Corr_lag_+2h":
                    lag_results.iloc[8]["correlation"],

                "Corr_lag_+3h":
                    lag_results.iloc[9]["correlation"],

                "Corr_lag_+4h":
                    lag_results.iloc[10]["correlation"],

                "Corr_lag_+5h":
                    lag_results.iloc[11]["correlation"],

                "Corr_lag_+6h":
                    lag_results.iloc[12]["correlation"],



                "Best_lag":
                    f"{int(best['lag'])}h",


                "Best_corr":
                    best["correlation"]

            }

        )




    # SUMMARY CSV



    summary = pd.DataFrame(
        global_summary
    )


    print("\n\n")
    print("=" * 80)
    print("SUMMARY ALL SITES")
    print("=" * 80)


    print(
        summary.to_string(index=False)
    )






    # QUALITY JSON



    quality_data = {}



    for item in global_summary:


        site = item["Site"]


        quality_data[site] = {


            "validation_variable":
                "shortwave_radiation",


            "correlation_lag": {


                "-6h":
                    item["Corr_lag_-6h"],

                "-5h":
                    item["Corr_lag_-5h"],

                "-4h":
                    item["Corr_lag_-4h"],

                "-3h":
                    item["Corr_lag_-3h"],

                "-2h":
                    item["Corr_lag_-2h"],

                "-1h":
                    item["Corr_lag_-1h"],


                "0h":
                    item["Corr_lag_0h"],


                "+1h":
                    item["Corr_lag_+1h"],

                "+2h":
                    item["Corr_lag_+2h"],

                "+3h":
                    item["Corr_lag_+3h"],

                "+4h":
                    item["Corr_lag_+4h"],

                "+5h":
                    item["Corr_lag_+5h"],

                "+6h":
                    item["Corr_lag_+6h"],

            },


            "best_lag":
                item["Best_lag"],


            "best_correlation":
                item["Best_corr"],



            "timezone_validation":
                (
                    "PASS"
                    if item["Best_lag"] == "0h"
                    else "CHECK"
                )

        }



    with open(
        QUALITY_FILE / "quality.json",
        "w",
        encoding="utf-8"
    ) as f:


        json.dump(
            quality_data,
            f,
            indent=4,
            ensure_ascii=False
        )



    print(
        "\nQuality report saved : quality.json"
    )

    print(
        "CSV report saved : lag_correlation_all_sites.csv"
    )




# MAIN


if __name__ == "__main__":

    verify_sites()