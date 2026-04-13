import json
from typing import Any

import azure.functions as func


def cors_headers(origin: str | None = None) -> dict[str, str]:
    allow_origin = origin or "*"
    return {
        "Access-Control-Allow-Origin": allow_origin,
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Max-Age": "86400",
    }


def json_response(
    body: Any,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> func.HttpResponse:
    out_headers = {"Content-Type": "application/json; charset=utf-8"}
    if headers:
        out_headers.update(headers)
    return func.HttpResponse(
        body=json.dumps(body),
        status_code=status_code,
        headers=out_headers,
    )

