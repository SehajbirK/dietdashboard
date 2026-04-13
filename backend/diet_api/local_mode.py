from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass

import pandas as pd

from .diets import clean_diets_df, compute_all


@dataclass(frozen=True)
class LocalCachePaths:
    root: pathlib.Path
    meta_json: pathlib.Path
    clean_csv: pathlib.Path
    insights_json: pathlib.Path
    clusters_json: pathlib.Path


def local_cache_paths(root: str = "/tmp/diet_cache") -> LocalCachePaths:
    r = pathlib.Path(root)
    return LocalCachePaths(
        root=r,
        meta_json=r / "meta.json",
        clean_csv=r / "All_Diets_clean.csv",
        insights_json=r / "insights.json",
        clusters_json=r / "clusters.json",
    )


def _read_meta(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_meta(path: pathlib.Path, meta: dict) -> None:
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def ensure_local_precompute(*, source_csv_path: str, cache_root: str = "/tmp/diet_cache") -> LocalCachePaths:
    paths = local_cache_paths(cache_root)
    paths.root.mkdir(parents=True, exist_ok=True)

    src = pathlib.Path(source_csv_path)
    if not src.is_absolute():
        # Interpret relative to the Azure Functions project root (backend/)
        src = (pathlib.Path(__file__).resolve().parent.parent / src).resolve()

    if not src.exists():
        raise FileNotFoundError(f"Local CSV not found: {src}")

    mtime = int(src.stat().st_mtime)
    meta = _read_meta(paths.meta_json)
    if meta.get("source_path") == str(src) and int(meta.get("source_mtime") or 0) == mtime:
        # Cache is current.
        return paths

    df_raw = pd.read_csv(src)
    df_clean = clean_diets_df(df_raw)
    pre = compute_all(df_clean)

    paths.clean_csv.write_text(df_clean.to_csv(index=False), encoding="utf-8")
    paths.insights_json.write_text(json.dumps(pre.insights), encoding="utf-8")
    paths.clusters_json.write_text(json.dumps(pre.clusters), encoding="utf-8")

    _write_meta(
        paths.meta_json,
        {
            "source_path": str(src),
            "source_mtime": mtime,
            "computed_at": pre.computed_at_iso,
        },
    )
    return paths


def read_local_insights(paths: LocalCachePaths) -> dict:
    return json.loads(paths.insights_json.read_text(encoding="utf-8"))


def read_local_clusters(paths: LocalCachePaths) -> list:
    return json.loads(paths.clusters_json.read_text(encoding="utf-8"))


def read_local_clean_df(paths: LocalCachePaths) -> pd.DataFrame:
    return pd.read_csv(paths.clean_csv)

