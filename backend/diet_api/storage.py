import io
from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd
from azure.data.tables import TableServiceClient
from azure.storage.blob import BlobClient, BlobProperties, BlobServiceClient
from azure.storage.blob import ContentSettings


@dataclass
class BlobObject:
    bytes: bytes
    etag: str | None
    last_modified_iso: str | None


def blob_service(connection_string: str) -> BlobServiceClient:
    return BlobServiceClient.from_connection_string(connection_string)


def ensure_container(blob_svc: BlobServiceClient, container: str) -> None:
    container_client = blob_svc.get_container_client(container)
    try:
        container_client.create_container()
    except Exception:
        pass


def download_blob_bytes(
    blob_svc: BlobServiceClient, *, container: str, blob: str
) -> BlobObject:
    blob_client: BlobClient = blob_svc.get_blob_client(container=container, blob=blob)
    props: BlobProperties = blob_client.get_blob_properties()
    data = blob_client.download_blob().readall()
    etag = getattr(props, "etag", None)
    lm = getattr(props, "last_modified", None)
    return BlobObject(
        bytes=data,
        etag=str(etag) if etag else None,
        last_modified_iso=lm.isoformat() if lm else None,
    )


def upload_blob_bytes(
    blob_svc: BlobServiceClient,
    *,
    container: str,
    blob: str,
    data: bytes,
    content_type: str,
    metadata: Optional[dict[str, str]] = None,
) -> None:
    ensure_container(blob_svc, container)
    blob_client: BlobClient = blob_svc.get_blob_client(container=container, blob=blob)
    blob_client.upload_blob(
        data=data,
        overwrite=True,
        content_settings=ContentSettings(content_type=content_type),
        metadata=metadata,
    )


def table_service(connection_string: str) -> TableServiceClient:
    return TableServiceClient.from_connection_string(connection_string)


def ensure_table(table_svc: TableServiceClient, table_name: str) -> None:
    try:
        table_svc.create_table_if_not_exists(table_name=table_name)
    except Exception:
        pass


def df_from_csv_bytes(csv_bytes: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(csv_bytes))


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")
