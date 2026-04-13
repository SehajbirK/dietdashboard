from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

import pandas as pd


def _title_diet(diet: str) -> str:
    d = (diet or "").strip()
    if d == "":
        return "Unknown"
    return d[:1].upper() + d[1:].lower()


def clean_diets_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    # Normalize key column names if needed.
    if "Diet_type" not in out.columns and "diet_type" in out.columns:
        out = out.rename(columns={"diet_type": "Diet_type"})
    if "Recipe_name" not in out.columns and "recipe_name" in out.columns:
        out = out.rename(columns={"recipe_name": "Recipe_name"})
    if "Cuisine_type" not in out.columns and "cuisine_type" in out.columns:
        out = out.rename(columns={"cuisine_type": "Cuisine_type"})

    for col in ("Protein(g)", "Carbs(g)", "Fat(g)"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    out["Diet_type"] = out.get("Diet_type", "").astype(str).map(_title_diet)
    out["Recipe_name"] = out.get("Recipe_name", "").astype(str)
    out["Cuisine_type"] = out.get("Cuisine_type", "").astype(str)

    out.fillna(out.mean(numeric_only=True), inplace=True)

    # Derived fields used by the UI.
    if all(c in out.columns for c in ("Protein(g)", "Carbs(g)", "Fat(g)")):
        out["Calories"] = (out["Protein(g)"] * 4) + (out["Carbs(g)"] * 4) + (out["Fat(g)"] * 9)

    return out


def _assign_cluster(row: pd.Series) -> int:
    protein = float(row.get("Protein(g)", 0.0) or 0.0)
    carbs = float(row.get("Carbs(g)", 0.0) or 0.0)
    fat = float(row.get("Fat(g)", 0.0) or 0.0)

    if protein >= carbs and protein >= fat:
        return 0
    if carbs >= protein and carbs >= fat:
        return 1
    return 2


@dataclass(frozen=True)
class Precomputed:
    cleaned_df: pd.DataFrame
    insights: dict
    clusters: list[dict]
    computed_at_iso: str


def compute_all(df_clean: pd.DataFrame) -> Precomputed:
    computed_at_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    # Insights for charts.
    avg = (
        df_clean.groupby("Diet_type")[["Protein(g)", "Carbs(g)", "Fat(g)"]]
        .mean(numeric_only=True)
        .reset_index()
    )

    bar_chart = [
        {"diet": row["Diet_type"], "protein": round(float(row["Protein(g)"]), 2)}
        for _, row in avg.iterrows()
    ]
    pie_chart = [
        {"diet": row["Diet_type"], "fat": round(float(row["Fat(g)"]), 2)}
        for _, row in avg.iterrows()
    ]

    scatter_src = df_clean[["Carbs(g)", "Protein(g)"]].dropna()
    scatter_src = scatter_src.head(400)
    scatter_chart = [
        {"carbs": round(float(r["Carbs(g)"]), 2), "protein": round(float(r["Protein(g)"]), 2)}
        for _, r in scatter_src.iterrows()
    ]

    insights = {
        "computed_at": computed_at_iso,
        "bar_chart": bar_chart,
        "pie_chart": pie_chart,
        "scatter_chart": scatter_chart,
    }

    # Cluster output.
    df_clusters = df_clean.copy()
    df_clusters["cluster"] = df_clusters.apply(_assign_cluster, axis=1)

    clusters = [
        {
            "recipe": str(r.get("Recipe_name", "")),
            "diet": str(r.get("Diet_type", "")),
            "cluster": int(r.get("cluster", 0)),
        }
        for _, r in df_clusters[["Recipe_name", "Diet_type", "cluster"]].head(200).iterrows()
    ]

    return Precomputed(
        cleaned_df=df_clean,
        insights=insights,
        clusters=clusters,
        computed_at_iso=computed_at_iso,
    )


def normalize_search(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t

