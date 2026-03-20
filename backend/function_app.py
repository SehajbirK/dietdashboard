import io
import json
import os
import tempfile
from typing import Any, Dict, Optional

import azure.functions as func
import pandas as pd
from azure.storage.blob import BlobServiceClient

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

def _cors_headers() -> Dict[str, str]:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


def _get_connection_string() -> Optional[str]:
    return (
        os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        or os.getenv("AzureWebJobsStorage")
        or os.getenv("AZURE_STORAGE_CONNECTION")
    )


def _process_csv_bytes(csv_bytes: bytes) -> Dict[str, Any]:
    df = pd.read_csv(io.BytesIO(csv_bytes))

    df["Protein(g)"] = pd.to_numeric(df["Protein(g)"], errors="coerce")
    df["Carbs(g)"] = pd.to_numeric(df["Carbs(g)"], errors="coerce")
    df["Fat(g)"] = pd.to_numeric(df["Fat(g)"], errors="coerce")
    df.fillna(df.mean(numeric_only=True), inplace=True)

    avg_macros = df.groupby("Diet_type")[["Protein(g)", "Carbs(g)", "Fat(g)"]].mean()
    return {"results": avg_macros.reset_index().to_dict(orient="records")}


def _seed_blob_if_local_file_exists(
    blob_service_client: BlobServiceClient, *, container_name: str, blob_name: str
) -> None:
    local_csv_path = os.getenv("LOCAL_CSV_PATH", "data/All_Diets.csv")
    if not os.path.exists(local_csv_path):
        return

    container_client = blob_service_client.get_container_client(container_name)
    try:
        container_client.create_container()
    except Exception:
        pass

    with open(local_csv_path, "rb") as data:
        container_client.upload_blob(name=blob_name, data=data, overwrite=True)


@app.route(route="process", methods=["POST", "GET"])
def process(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=_cors_headers())

    container_name = os.getenv("BLOB_CONTAINER_NAME", "datasets")
    blob_name = os.getenv("BLOB_NAME", "All_Diets.csv")

    connect_str = _get_connection_string()
    if not connect_str:
        return func.HttpResponse(
            "Missing storage connection string. Set AZURE_STORAGE_CONNECTION_STRING (or AzureWebJobsStorage).",
            status_code=500,
            headers=_cors_headers(),
        )

    try:
        blob_service_client = BlobServiceClient.from_connection_string(connect_str)
        _seed_blob_if_local_file_exists(
            blob_service_client, container_name=container_name, blob_name=blob_name
        )

        blob_client = blob_service_client.get_blob_client(
            container=container_name, blob=blob_name
        )
        csv_bytes = blob_client.download_blob().readall()

        payload = _process_csv_bytes(csv_bytes)

        out_dir = os.path.join(tempfile.gettempdir(), "simulated_nosql")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "results.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload["results"], f, indent=4)

        return func.HttpResponse(
            body=json.dumps(payload),
            mimetype="application/json",
            status_code=200,
            headers=_cors_headers(),
        )
    except Exception as e:
        return func.HttpResponse(
            f"Processing failed: {e}", status_code=500, headers=_cors_headers()
        )
