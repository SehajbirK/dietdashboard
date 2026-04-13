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

    return Settings(
        storage_connection_string=storage_connection_string,
        diets_container=_env("DIETS_CONTAINER", "datasets") or "datasets",
        diets_blob=_env("DIETS_BLOB", "All_Diets.csv") or "All_Diets.csv",
        clean_container=_env("DIETS_CLEAN_CONTAINER", "datasets-clean") or "datasets-clean",
        clean_blob=_env("DIETS_CLEAN_BLOB", "All_Diets_clean.csv") or "All_Diets_clean.csv",
        cache_container=_env("DIETS_CACHE_CONTAINER", "datasets-cache") or "datasets-cache",
        insights_blob=_env("INSIGHTS_BLOB", "insights.json") or "insights.json",
        clusters_blob=_env("CLUSTERS_BLOB", "clusters.json") or "clusters.json",
        users_table_name=_env("USERS_TABLE_NAME", "diet-users") or "diet-users",
        jwt_secret=_env("JWT_SECRET"),
        jwt_issuer=_env("JWT_ISSUER", "diet-dashboard") or "diet-dashboard",
        jwt_audience=_env("JWT_AUDIENCE", "diet-dashboard") or "diet-dashboard",
        jwt_ttl_seconds=jwt_ttl_seconds,
        github_client_id=_env("GITHUB_CLIENT_ID"),
        github_client_secret=_env("GITHUB_CLIENT_SECRET"),
        github_scopes=_env("GITHUB_SCOPES", "read:user user:email") or "read:user user:email",
    )

