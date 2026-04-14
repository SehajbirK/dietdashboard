import json
import logging
import os
from typing import Any

import azure.functions as func
import pandas as pd

from diet_api.auth import (
    build_oauth_state,
    extract_bearer_token,
    github_exchange_code,
    github_fetch_primary_email,
    github_fetch_user,
    github_oauth_start_url,
    issue_token,
    login_local_user,
    login_local_user_sqlite,
    logout_user,
    logout_user_sqlite,
    parse_oauth_state,
    register_local_user,
    register_local_user_sqlite,
    sqlite_connect,
    upsert_github_user,
    upsert_github_user_sqlite,
    users_table,
    validate_request_token,
    validate_request_token_sqlite,
)
from diet_api.config import load_settings
from diet_api.diets import clean_diets_df, compute_all, normalize_search
from diet_api.http import cors_headers, json_response
from diet_api.storage import (
    blob_service,
    df_from_csv_bytes,
    df_to_csv_bytes,
    download_blob_bytes,
    table_service,
    upload_blob_bytes,
)
from diet_api.local_mode import (
    ensure_local_precompute,
    read_local_clean_df,
    read_local_clusters,
    read_local_insights,
)

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
settings = load_settings()

_CLEAN_DF_CACHE: dict[str, Any] = {"etag": None, "df": None}
_INSIGHTS_CACHE: dict[str, Any] = {"etag": None, "json": None}
_CLUSTERS_CACHE: dict[str, Any] = {"etag": None, "json": None}


def _origin(req: func.HttpRequest) -> str | None:
    return req.headers.get("Origin")


def _require_storage() -> str:
    if settings.local_dev_mode:
        raise ValueError("Storage not used in LOCAL_DEV_MODE.")
    if not settings.storage_connection_string:
        raise ValueError(
            "Missing storage connection string. Set AZURE_STORAGE_CONNECTION_STRING (or AzureWebJobsStorage)."
        )
    return settings.storage_connection_string


def _require_jwt_secret() -> str:
    if not settings.jwt_secret:
        raise ValueError("Missing JWT_SECRET.")
    return settings.jwt_secret


def _table_client():
    tsvc = table_service(_require_storage())
    return users_table(tsvc, settings.users_table_name)


def _require_auth(req: func.HttpRequest):
    token = extract_bearer_token(req.headers.get("Authorization"))
    if not token:
        raise PermissionError("Missing Bearer token.")
    try:
        if settings.local_dev_mode:
            conn = sqlite_connect(settings.sqlite_path)
            try:
                return validate_request_token_sqlite(
                    token=token,
                    conn=conn,
                    jwt_secret=_require_jwt_secret(),
                    jwt_issuer=settings.jwt_issuer,
                    jwt_audience=settings.jwt_audience,
                )
            finally:
                conn.close()
        else:
            return validate_request_token(
                token=token,
                table=_table_client(),
                jwt_secret=_require_jwt_secret(),
                jwt_issuer=settings.jwt_issuer,
                jwt_audience=settings.jwt_audience,
            )
    except PermissionError:
        raise
    except Exception as e:
        raise PermissionError(str(e))


def _load_cached_json(*, container: str, blob: str, cache: dict[str, Any]) -> dict[str, Any]:
    if settings.local_dev_mode:
        paths = ensure_local_precompute(source_csv_path=settings.local_csv_path)
        if blob == settings.insights_blob:
            return read_local_insights(paths)
        if blob == settings.clusters_blob:
            return read_local_clusters(paths)
        raise FileNotFoundError("Unknown local cache blob")
    bsvc = blob_service(_require_storage())
    obj = download_blob_bytes(bsvc, container=container, blob=blob)
    if cache.get("etag") == obj.etag and cache.get("json") is not None:
        return cache["json"]
    payload = json.loads(obj.bytes.decode("utf-8"))
    cache["etag"] = obj.etag
    cache["json"] = payload
    return payload


def _load_clean_df() -> pd.DataFrame:
    if settings.local_dev_mode:
        paths = ensure_local_precompute(source_csv_path=settings.local_csv_path)
        return read_local_clean_df(paths)
    bsvc = blob_service(_require_storage())
    obj = download_blob_bytes(bsvc, container=settings.clean_container, blob=settings.clean_blob)
    if _CLEAN_DF_CACHE.get("etag") == obj.etag and _CLEAN_DF_CACHE.get("df") is not None:
        return _CLEAN_DF_CACHE["df"]
    df = df_from_csv_bytes(obj.bytes)
    _CLEAN_DF_CACHE["etag"] = obj.etag
    _CLEAN_DF_CACHE["df"] = df
    return df


if not settings.local_dev_mode:
    @app.function_name(name="diets_blob_trigger")
    @app.blob_trigger(
        arg_name="diets_blob",
        path="%DIETS_CONTAINER%/%DIETS_BLOB%",
        connection="AzureWebJobsStorage",
    )
    def diets_blob_trigger(diets_blob: func.InputStream) -> None:
        """
        Runs only when DIETS_CONTAINER/DIETS_BLOB changes.
        Cleans data once and writes cleaned CSV + precomputed JSON to durable blob storage.
        """
        try:
            storage = _require_storage()
            bsvc = blob_service(storage)

            csv_bytes = diets_blob.read()
            df_raw = df_from_csv_bytes(csv_bytes)
            df_clean = clean_diets_df(df_raw)
            pre = compute_all(df_clean)

            upload_blob_bytes(
                bsvc,
                container=settings.clean_container,
                blob=settings.clean_blob,
                data=df_to_csv_bytes(pre.cleaned_df),
                content_type="text/csv",
                metadata={"computed_at": pre.computed_at_iso},
            )

            upload_blob_bytes(
                bsvc,
                container=settings.cache_container,
                blob=settings.insights_blob,
                data=json.dumps(pre.insights).encode("utf-8"),
                content_type="application/json",
                metadata={"computed_at": pre.computed_at_iso},
            )

            upload_blob_bytes(
                bsvc,
                container=settings.cache_container,
                blob=settings.clusters_blob,
                data=json.dumps(pre.clusters).encode("utf-8"),
                content_type="application/json",
                metadata={"computed_at": pre.computed_at_iso},
            )

            logging.info(
                "Precompute complete. Wrote %s/%s and %s/%s (computed_at=%s).",
                settings.clean_container,
                settings.clean_blob,
                settings.cache_container,
                settings.insights_blob,
                pre.computed_at_iso,
            )
        except Exception as e:
            logging.exception("Blob trigger failed: %s", e)


@app.route(route="health", methods=["GET", "OPTIONS"])
def api_health(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers(_origin(req)))
    return json_response(
        {
            "ok": True,
            "local_dev_mode": bool(settings.local_dev_mode),
            "users_table_name": settings.users_table_name,
            "storage_configured": bool(settings.storage_connection_string),
        },
        headers=cors_headers(_origin(req)),
    )


@app.route(route="auth/register", methods=["POST", "OPTIONS"])
def api_register(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers(_origin(req)))
    try:
        body = req.get_json()
        if settings.local_dev_mode:
            conn = sqlite_connect(settings.sqlite_path)
            try:
                user = register_local_user_sqlite(
                    conn=conn,
                    email=str(body.get("email") or ""),
                    password=str(body.get("password") or ""),
                    name=str(body.get("name") or ""),
                )
            finally:
                conn.close()
        else:
            user = register_local_user(
                table=_table_client(),
                email=str(body.get("email") or ""),
                password=str(body.get("password") or ""),
                name=str(body.get("name") or ""),
            )
        token = issue_token(
            user=user,
            jwt_secret=settings.jwt_secret,
            jwt_issuer=settings.jwt_issuer,
            jwt_audience=settings.jwt_audience,
            jwt_ttl_seconds=settings.jwt_ttl_seconds,
        )
        return json_response(
            {"token": token, "user": {"name": user.name, "email": user.email, "provider": user.provider}},
            headers=cors_headers(_origin(req)),
        )
    except ValueError as e:
        return json_response({"error": str(e)}, status_code=400, headers=cors_headers(_origin(req)))
    except Exception as e:
        return json_response({"error": f"Registration failed: {e}"}, status_code=500, headers=cors_headers(_origin(req)))


@app.route(route="auth/login", methods=["POST", "OPTIONS"])
def api_login(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers(_origin(req)))
    try:
        body = req.get_json()
        if settings.local_dev_mode:
            conn = sqlite_connect(settings.sqlite_path)
            try:
                user = login_local_user_sqlite(
                    conn=conn,
                    email=str(body.get("email") or ""),
                    password=str(body.get("password") or ""),
                )
            finally:
                conn.close()
        else:
            user = login_local_user(
                table=_table_client(),
                email=str(body.get("email") or ""),
                password=str(body.get("password") or ""),
            )
        token = issue_token(
            user=user,
            jwt_secret=settings.jwt_secret,
            jwt_issuer=settings.jwt_issuer,
            jwt_audience=settings.jwt_audience,
            jwt_ttl_seconds=settings.jwt_ttl_seconds,
        )
        return json_response(
            {"token": token, "user": {"name": user.name, "email": user.email, "provider": user.provider}},
            headers=cors_headers(_origin(req)),
        )
    except PermissionError as e:
        return json_response({"error": str(e)}, status_code=401, headers=cors_headers(_origin(req)))
    except Exception as e:
        return json_response({"error": f"Login failed: {e}"}, status_code=500, headers=cors_headers(_origin(req)))


@app.route(route="auth/logout", methods=["POST", "OPTIONS"])
def api_logout(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers(_origin(req)))
    try:
        user = _require_auth(req)
        if settings.local_dev_mode:
            conn = sqlite_connect(settings.sqlite_path)
            try:
                new_tv = logout_user_sqlite(conn=conn, user_id=user.user_id)
            finally:
                conn.close()
        else:
            new_tv = logout_user(table=_table_client(), user_id=user.user_id)
        return json_response({"ok": True, "token_version": new_tv}, headers=cors_headers(_origin(req)))
    except PermissionError as e:
        return json_response({"error": str(e)}, status_code=401, headers=cors_headers(_origin(req)))
    except Exception as e:
        return json_response({"error": f"Logout failed: {e}"}, status_code=500, headers=cors_headers(_origin(req)))


@app.route(route="me", methods=["GET", "OPTIONS"])
def api_me(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers(_origin(req)))
    try:
        user = _require_auth(req)
        return json_response(
            {"user": {"name": user.name, "email": user.email, "provider": user.provider}},
            headers=cors_headers(_origin(req)),
        )
    except PermissionError as e:
        return json_response({"error": str(e)}, status_code=401, headers=cors_headers(_origin(req)))
    except Exception as e:
        return json_response({"error": f"Me failed: {e}"}, status_code=500, headers=cors_headers(_origin(req)))


@app.route(route="oauth/github/start", methods=["GET", "OPTIONS"])
def api_oauth_github_start(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers(_origin(req)))
    try:
        if not settings.github_client_id or not settings.github_client_secret:
            return json_response({"error": "GitHub OAuth is not configured."}, status_code=500, headers=cors_headers(_origin(req)))

        return_to = req.params.get("return_to") or req.params.get("returnTo") or ""
        if not return_to:
            return_to = "http://localhost:5000/"

        secret = _require_jwt_secret()
        state = build_oauth_state(jwt_secret=secret, return_to=return_to)

        callback_url = (req.url.split("?", 1)[0]).replace("/start", "/callback")
        url = github_oauth_start_url(
            github_client_id=settings.github_client_id,
            scopes=settings.github_scopes,
            callback_url=callback_url,
            state=state,
        )
        return func.HttpResponse(status_code=302, headers={"Location": url, **cors_headers(_origin(req))})
    except Exception as e:
        return json_response({"error": f"OAuth start failed: {e}"}, status_code=500, headers=cors_headers(_origin(req)))


@app.route(route="oauth/github/callback", methods=["GET", "OPTIONS"])
def api_oauth_github_callback(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers(_origin(req)))
    try:
        if not settings.github_client_id or not settings.github_client_secret:
            return json_response({"error": "GitHub OAuth is not configured."}, status_code=500, headers=cors_headers(_origin(req)))

        code = req.params.get("code") or ""
        state = req.params.get("state") or ""
        if not code or not state:
            return json_response({"error": "Missing code/state."}, status_code=400, headers=cors_headers(_origin(req)))

        secret = _require_jwt_secret()
        state_data = parse_oauth_state(jwt_secret=secret, state=state)
        return_to = str(state_data.get("return_to") or "http://localhost:5000/")

        callback_url = req.url.split("?", 1)[0]
        access_token = github_exchange_code(
            client_id=settings.github_client_id,
            client_secret=settings.github_client_secret,
            code=code,
            callback_url=callback_url,
        )
        gh_user = github_fetch_user(access_token)
        email = github_fetch_primary_email(access_token)
        if settings.local_dev_mode:
            conn = sqlite_connect(settings.sqlite_path)
            try:
                user = upsert_github_user_sqlite(conn=conn, github_user=gh_user, email=email)
            finally:
                conn.close()
        else:
            user = upsert_github_user(table=_table_client(), github_user=gh_user, email=email)
        token = issue_token(
            user=user,
            jwt_secret=settings.jwt_secret,
            jwt_issuer=settings.jwt_issuer,
            jwt_audience=settings.jwt_audience,
            jwt_ttl_seconds=settings.jwt_ttl_seconds,
        )

        # Redirect back to the frontend with the token in the URL fragment.
        redirect_url = f"{return_to}#token={token}"
        return func.HttpResponse(status_code=302, headers={"Location": redirect_url, **cors_headers(_origin(req))})
    except PermissionError as e:
        return json_response({"error": str(e)}, status_code=401, headers=cors_headers(_origin(req)))
    except Exception as e:
        return json_response({"error": f"OAuth callback failed: {e}"}, status_code=500, headers=cors_headers(_origin(req)))


@app.route(route="insights", methods=["GET", "OPTIONS"])
def api_insights(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers(_origin(req)))
    try:
        _ = _require_auth(req)
        data = _load_cached_json(
            container=settings.cache_container,
            blob=settings.insights_blob,
            cache=_INSIGHTS_CACHE,
        )
        return json_response(data, headers=cors_headers(_origin(req)))
    except PermissionError as e:
        return json_response({"error": str(e)}, status_code=401, headers=cors_headers(_origin(req)))
    except Exception as e:
        return json_response({"error": f"Insights not ready: {e}"}, status_code=503, headers=cors_headers(_origin(req)))


@app.route(route="clusters", methods=["GET", "OPTIONS"])
def api_clusters(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers(_origin(req)))
    try:
        _ = _require_auth(req)
        data = _load_cached_json(
            container=settings.cache_container,
            blob=settings.clusters_blob,
            cache=_CLUSTERS_CACHE,
        )
        return json_response(data, headers=cors_headers(_origin(req)))
    except PermissionError as e:
        return json_response({"error": str(e)}, status_code=401, headers=cors_headers(_origin(req)))
    except Exception as e:
        return json_response({"error": f"Clusters not ready: {e}"}, status_code=503, headers=cors_headers(_origin(req)))


@app.route(route="recipes", methods=["GET", "OPTIONS"])
def api_recipes(req: func.HttpRequest) -> func.HttpResponse:
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers(_origin(req)))
    try:
        _ = _require_auth(req)

        page = int(req.params.get("page") or "1")
        page_size = int(req.params.get("pageSize") or req.params.get("page_size") or "10")
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 10
        if page_size > 100:
            page_size = 100

        diet = (req.params.get("diet") or "").strip()
        search = normalize_search(req.params.get("search") or "")

        df = _load_clean_df()

        out = df
        if diet:
            out = out[out["Diet_type"].astype(str).str.lower() == diet.strip().lower()]
        if search:
            hay = (
                out["Recipe_name"].astype(str)
                + " "
                + out["Cuisine_type"].astype(str)
                + " "
                + out["Diet_type"].astype(str)
            ).str.lower()
            out = out[hay.str.contains(search, na=False)]

        out = out.sort_values(["Recipe_name", "Cuisine_type"], kind="mergesort")

        total = int(len(out))
        total_pages = int((total + page_size - 1) // page_size) if total > 0 else 0
        if total_pages > 0 and page > total_pages:
            page = total_pages

        start = (page - 1) * page_size
        end = start + page_size
        page_df = out.iloc[start:end]

        items = []
        for _, r in page_df.iterrows():
            items.append(
                {
                    "recipe": str(r.get("Recipe_name", "")),
                    "diet": str(r.get("Diet_type", "")),
                    "cuisine": str(r.get("Cuisine_type", "")),
                    "calories": round(float(r.get("Calories", 0) or 0), 2),
                    "protein": round(float(r.get("Protein(g)", 0) or 0), 2),
                    "carbs": round(float(r.get("Carbs(g)", 0) or 0), 2),
                    "fat": round(float(r.get("Fat(g)", 0) or 0), 2),
                }
            )

        return json_response(
            {
                "page": page,
                "pageSize": page_size,
                "totalPages": total_pages,
                "totalResults": total,
                "items": items,
            },
            headers=cors_headers(_origin(req)),
        )
    except PermissionError as e:
        return json_response({"error": str(e)}, status_code=401, headers=cors_headers(_origin(req)))
    except Exception as e:
        return json_response({"error": f"Recipes not ready: {e}"}, status_code=503, headers=cors_headers(_origin(req)))
