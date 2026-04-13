import os

from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobServiceClient


def _env(name: str, default: str | None = None) -> str:
    v = os.getenv(name)
    if v is None or v == "":
        if default is None:
            raise SystemExit(f"Missing env var: {name}")
        return default
    return v


def main() -> None:
    conn = _env("AZURE_STORAGE_CONNECTION_STRING", _env("AzureWebJobsStorage", "UseDevelopmentStorage=true"))
    users_table = _env("USERS_TABLE_NAME", "dietusers")
    containers = [
        _env("DIETS_CONTAINER", "datasets"),
        _env("DIETS_CLEAN_CONTAINER", "datasets-clean"),
        _env("DIETS_CACHE_CONTAINER", "datasets-cache"),
    ]

    bsvc = BlobServiceClient.from_connection_string(conn)
    for c in containers:
        try:
            bsvc.create_container(c)
            print(f"Created container: {c}")
        except Exception:
            print(f"Container exists: {c}")

    tsvc = TableServiceClient.from_connection_string(conn)
    tsvc.create_table_if_not_exists(table_name=users_table)
    print(f"Ensured table: {users_table}")


if __name__ == "__main__":
    main()
