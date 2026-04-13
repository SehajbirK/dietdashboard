import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str | None:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    return val


@dataclass(frozen=True)
class Settings:
    storage_connection_string: str | None
    local_dev_mode: bool
    local_csv_path: str
    sqlite_path: str

    diets_container: str
    diets_blob: str

    clean_container: str
    clean_blob: str

    cache_container: str
    insights_blob: str
    clusters_blob: str

    users_table_name: str

    jwt_secret: str | None
    jwt_issuer: str
    jwt_audience: str
    jwt_ttl_seconds: int

    github_client_id: str | None
    github_client_secret: str | None
    github_scopes: str


def load_settings() -> Settings:
    storage_connection_string = (
        _env("AZURE_STORAGE_CONNECTION_STRING")
        or _env("AzureWebJobsStorage")
        or _env("AZURE_STORAGE_CONNECTION")
    )

    jwt_ttl_seconds = int(_env("JWT_TTL_SECONDS", "3600") or "3600")
    local_dev_mode = (_env("LOCAL_DEV_MODE", "0") or "0").strip().lower() in ("1", "true", "yes", "on")
    local_csv_path = _env("LOCAL_CSV_PATH", "data/All_Diets.csv") or "data/All_Diets.csv"
    sqlite_path = _env("SQLITE_PATH", "/tmp/diet_dashboard.sqlite") or "/tmp/diet_dashboard.sqlite"

    return Settings(
        storage_connection_string=storage_connection_string,
        local_dev_mode=local_dev_mode,
        local_csv_path=local_csv_path,
        sqlite_path=sqlite_path,
        diets_container=_env("DIETS_CONTAINER", "datasets") or "datasets",
        diets_blob=_env("DIETS_BLOB", "All_Diets.csv") or "All_Diets.csv",
        clean_container=_env("DIETS_CLEAN_CONTAINER", "datasets-clean") or "datasets-clean",
        clean_blob=_env("DIETS_CLEAN_BLOB", "All_Diets_clean.csv") or "All_Diets_clean.csv",
        cache_container=_env("DIETS_CACHE_CONTAINER", "datasets-cache") or "datasets-cache",
        insights_blob=_env("INSIGHTS_BLOB", "insights.json") or "insights.json",
        clusters_blob=_env("CLUSTERS_BLOB", "clusters.json") or "clusters.json",
        # Azure Table names must be alphanumeric and start with a letter (no hyphens).
        users_table_name=_env("USERS_TABLE_NAME", "dietusers") or "dietusers",
        jwt_secret=_env("JWT_SECRET"),
        jwt_issuer=_env("JWT_ISSUER", "diet-dashboard") or "diet-dashboard",
        jwt_audience=_env("JWT_AUDIENCE", "diet-dashboard") or "diet-dashboard",
        jwt_ttl_seconds=jwt_ttl_seconds,
        github_client_id=_env("GITHUB_CLIENT_ID"),
        github_client_secret=_env("GITHUB_CLIENT_SECRET"),
        github_scopes=_env("GITHUB_SCOPES", "read:user user:email") or "read:user user:email",
    )
