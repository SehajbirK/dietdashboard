import os
from pathlib import Path

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
    container = _env("DIETS_CONTAINER", "datasets")
    blob = _env("DIETS_BLOB", "All_Diets.csv")
    local_path = Path(_env("LOCAL_CSV_PATH", "data/All_Diets.csv"))

    if not local_path.exists():
        raise SystemExit(f"CSV not found: {local_path}")

    bsvc = BlobServiceClient.from_connection_string(conn)
    container_client = bsvc.get_container_client(container)
    try:
        container_client.create_container()
    except Exception:
        pass

    with local_path.open("rb") as f:
        container_client.upload_blob(name=blob, data=f, overwrite=True)

    print(f"Uploaded {local_path} -> {container}/{blob}")
    print("This should trigger the Blob Trigger function to clean + precompute caches.")


if __name__ == "__main__":
    main()

