from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import urllib.parse
from dataclasses import dataclass
from typing import Any, Optional

import bcrypt
import jwt
import requests
from azure.data.tables import TableClient, TableServiceClient
from azure.core.exceptions import ResourceNotFoundError
import sqlite3


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    email: str | None
    name: str
    provider: str
    token_version: int


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _require(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(f"Missing required setting: {name}")
    return value


def users_table(table_svc: TableServiceClient, table_name: str) -> TableClient:
    table_svc.create_table_if_not_exists(table_name=table_name)
    return table_svc.get_table_client(table_name=table_name)


def _user_row_key_local(email: str) -> str:
    return (email or "").strip().lower()


def _user_row_key_github(github_id: int) -> str:
    return f"github:{github_id}"


def _user_entity_to_auth_user(entity: dict[str, Any]) -> AuthUser:
    return AuthUser(
        user_id=str(entity["RowKey"]),
        email=entity.get("email"),
        name=entity.get("name") or "User",
        provider=entity.get("provider") or "local",
        token_version=int(entity.get("token_version") or 0),
    )


def _jwt_encode(
    *,
    secret: str,
    issuer: str,
    audience: str,
    user: AuthUser,
    ttl_seconds: int,
) -> str:
    now = _now_utc()
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": user.user_id,
        "email": user.email,
        "name": user.name,
        "provider": user.provider,
        "tv": user.token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _jwt_decode(
    token: str, *, secret: str, issuer: str, audience: str
) -> dict[str, Any]:
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        issuer=issuer,
        audience=audience,
        options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        leeway=10,
    )


def extract_bearer_token(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    parts = auth_header.split(" ", 1)
    if len(parts) != 2:
        return None
    if parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def validate_request_token(
    *,
    token: str,
    table: TableClient,
    jwt_secret: str,
    jwt_issuer: str,
    jwt_audience: str,
) -> AuthUser:
    payload = _jwt_decode(token, secret=jwt_secret, issuer=jwt_issuer, audience=jwt_audience)
    user_id = str(payload["sub"])
    tv = int(payload.get("tv") or 0)

    entity = table.get_entity(partition_key="USER", row_key=user_id)
    user = _user_entity_to_auth_user(entity)
    if user.token_version != tv:
        raise PermissionError("Token has been revoked.")
    return user


def sqlite_connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
          user_id TEXT PRIMARY KEY,
          email TEXT UNIQUE,
          name TEXT NOT NULL,
          provider TEXT NOT NULL,
          password_hash TEXT,
          provider_user_id TEXT,
          token_version INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _sqlite_get_user(conn: sqlite3.Connection, user_id: str) -> Optional[AuthUser]:
    row = conn.execute(
        "SELECT user_id, email, name, provider, token_version FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return AuthUser(
        user_id=str(row["user_id"]),
        email=row["email"],
        name=str(row["name"]),
        provider=str(row["provider"]),
        token_version=int(row["token_version"]),
    )


def validate_request_token_sqlite(
    *,
    token: str,
    conn: sqlite3.Connection,
    jwt_secret: str,
    jwt_issuer: str,
    jwt_audience: str,
) -> AuthUser:
    payload = _jwt_decode(token, secret=jwt_secret, issuer=jwt_issuer, audience=jwt_audience)
    user_id = str(payload["sub"])
    tv = int(payload.get("tv") or 0)
    user = _sqlite_get_user(conn, user_id)
    if not user:
        raise PermissionError("Unknown user.")
    if user.token_version != tv:
        raise PermissionError("Token has been revoked.")
    return user


def register_local_user_sqlite(
    *,
    conn: sqlite3.Connection,
    email: str,
    password: str,
    name: str,
) -> AuthUser:
    email_norm = _user_row_key_local(email)
    if "@" not in email_norm or "." not in email_norm:
        raise ValueError("Invalid email address.")
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters.")
    if len(name or "") < 1:
        raise ValueError("Name is required.")

    existing = conn.execute("SELECT 1 FROM users WHERE email = ?", (email_norm,)).fetchone()
    if existing:
        raise ValueError("User already exists.")

    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    created_at = _now_utc().isoformat()

    conn.execute(
        """
        INSERT INTO users (user_id, email, name, provider, password_hash, token_version, created_at)
        VALUES (?, ?, ?, 'local', ?, 0, ?)
        """,
        (email_norm, email_norm, name.strip(), pw_hash, created_at),
    )
    conn.commit()

    return AuthUser(
        user_id=email_norm,
        email=email_norm,
        name=name.strip(),
        provider="local",
        token_version=0,
    )


def login_local_user_sqlite(*, conn: sqlite3.Connection, email: str, password: str) -> AuthUser:
    email_norm = _user_row_key_local(email)
    row = conn.execute(
        "SELECT user_id, email, name, provider, password_hash, token_version FROM users WHERE user_id = ?",
        (email_norm,),
    ).fetchone()
    if not row:
        raise PermissionError("Invalid email or password.")
    if str(row["provider"]) != "local":
        raise PermissionError("Use OAuth to sign in for this account.")
    pw_hash = str(row["password_hash"] or "")
    if not pw_hash:
        raise PermissionError("Password login is not enabled for this account.")
    ok = bcrypt.checkpw(password.encode("utf-8"), pw_hash.encode("utf-8"))
    if not ok:
        raise PermissionError("Invalid email or password.")
    return AuthUser(
        user_id=str(row["user_id"]),
        email=row["email"],
        name=str(row["name"]),
        provider=str(row["provider"]),
        token_version=int(row["token_version"]),
    )


def logout_user_sqlite(*, conn: sqlite3.Connection, user_id: str) -> int:
    row = conn.execute("SELECT token_version FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        raise PermissionError("Unknown user.")
    tv = int(row["token_version"] or 0) + 1
    conn.execute("UPDATE users SET token_version = ? WHERE user_id = ?", (tv, user_id))
    conn.commit()
    return tv

def register_local_user(
    *,
    table: TableClient,
    email: str,
    password: str,
    name: str,
) -> AuthUser:
    email_norm = _user_row_key_local(email)
    if "@" not in email_norm or "." not in email_norm:
        raise ValueError("Invalid email address.")
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters.")
    if len(name or "") < 1:
        raise ValueError("Name is required.")

    try:
        _ = table.get_entity(partition_key="USER", row_key=email_norm)
    except ResourceNotFoundError:
        _ = None
    if _ is not None:
        raise ValueError("User already exists.")

    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    entity = {
        "PartitionKey": "USER",
        "RowKey": email_norm,
        "email": email_norm,
        "name": name.strip(),
        "provider": "local",
        "password_hash": pw_hash,
        "created_at": _now_utc().isoformat(),
        "token_version": 0,
    }
    table.upsert_entity(mode="replace", entity=entity)
    return _user_entity_to_auth_user(entity)


def login_local_user(*, table: TableClient, email: str, password: str) -> AuthUser:
    email_norm = _user_row_key_local(email)
    entity = table.get_entity(partition_key="USER", row_key=email_norm)
    if (entity.get("provider") or "local") != "local":
        raise PermissionError("Use OAuth to sign in for this account.")
    pw_hash = entity.get("password_hash") or ""
    if not pw_hash:
        raise PermissionError("Password login is not enabled for this account.")
    ok = bcrypt.checkpw(password.encode("utf-8"), pw_hash.encode("utf-8"))
    if not ok:
        raise PermissionError("Invalid email or password.")
    return _user_entity_to_auth_user(entity)


def issue_token(
    *,
    user: AuthUser,
    jwt_secret: str | None,
    jwt_issuer: str,
    jwt_audience: str,
    jwt_ttl_seconds: int,
) -> str:
    secret = _require(jwt_secret, "JWT_SECRET")
    return _jwt_encode(
        secret=secret,
        issuer=jwt_issuer,
        audience=jwt_audience,
        user=user,
        ttl_seconds=jwt_ttl_seconds,
    )


def logout_user(*, table: TableClient, user_id: str) -> int:
    entity = table.get_entity(partition_key="USER", row_key=user_id)
    tv = int(entity.get("token_version") or 0) + 1
    entity["token_version"] = tv
    table.upsert_entity(mode="replace", entity=entity)
    return tv


def _signed_state(secret: str, data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    packed = base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=") + "." + base64.urlsafe_b64encode(
        mac
    ).decode("utf-8").rstrip("=")
    return packed


def _verify_state(secret: str, state: str) -> dict[str, Any]:
    raw_b64, mac_b64 = (state or "").split(".", 1)
    raw = base64.urlsafe_b64decode(raw_b64 + "===")
    mac = base64.urlsafe_b64decode(mac_b64 + "===")
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise PermissionError("Invalid OAuth state.")
    return json.loads(raw.decode("utf-8"))


def github_oauth_start_url(
    *,
    github_client_id: str,
    scopes: str,
    callback_url: str,
    state: str,
) -> str:
    q = urllib.parse.urlencode(
        {
            "client_id": github_client_id,
            "redirect_uri": callback_url,
            "scope": scopes,
            "state": state,
        }
    )
    return f"https://github.com/login/oauth/authorize?{q}"


def github_exchange_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    callback_url: str,
) -> str:
    resp = requests.post(
        "https://github.com/login/oauth/access_token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": callback_url,
        },
        headers={"Accept": "application/json", "User-Agent": "diet-dashboard/1.0"},
        timeout=20,
    )
    payload = resp.json()
    token = payload.get("access_token")
    if not token:
        raise PermissionError("GitHub token exchange failed.")
    return str(token)


def github_fetch_user(access_token: str) -> dict[str, Any]:
    resp = requests.get(
        "https://api.github.com/user",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "diet-dashboard/1.0",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def github_fetch_primary_email(access_token: str) -> str | None:
    resp = requests.get(
        "https://api.github.com/user/emails",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "diet-dashboard/1.0",
        },
        timeout=20,
    )
    if resp.status_code >= 400:
        return None
    emails = resp.json()
    if not isinstance(emails, list):
        return None
    for e in emails:
        if e.get("primary") is True and e.get("verified") is True and e.get("email"):
            return str(e["email"])
    for e in emails:
        if e.get("verified") is True and e.get("email"):
            return str(e["email"])
    return None


def upsert_github_user(
    *,
    table: TableClient,
    github_user: dict[str, Any],
    email: str | None,
) -> AuthUser:
    github_id = int(github_user.get("id") or 0)
    if github_id <= 0:
        raise PermissionError("Missing GitHub user id.")

    user_id = _user_row_key_github(github_id)
    name = (
        (github_user.get("name") or "").strip()
        or (github_user.get("login") or "").strip()
        or "GitHub User"
    )

    try:
        entity = table.get_entity(partition_key="USER", row_key=user_id)
        entity["name"] = name
        entity["email"] = email or entity.get("email")
        entity["provider"] = "github"
        entity["provider_user_id"] = str(github_id)
        table.upsert_entity(mode="replace", entity=entity)
        return _user_entity_to_auth_user(entity)
    except ResourceNotFoundError:
        entity = {
            "PartitionKey": "USER",
            "RowKey": user_id,
            "email": email,
            "name": name,
            "provider": "github",
            "provider_user_id": str(github_id),
            "created_at": _now_utc().isoformat(),
            "token_version": 0,
        }
        table.upsert_entity(mode="replace", entity=entity)
        return _user_entity_to_auth_user(entity)


def upsert_github_user_sqlite(
    *,
    conn: sqlite3.Connection,
    github_user: dict[str, Any],
    email: str | None,
) -> AuthUser:
    github_id = int(github_user.get("id") or 0)
    if github_id <= 0:
        raise PermissionError("Missing GitHub user id.")

    user_id = _user_row_key_github(github_id)
    name = (
        (github_user.get("name") or "").strip()
        or (github_user.get("login") or "").strip()
        or "GitHub User"
    )

    existing = conn.execute(
        "SELECT user_id, email, name, provider, token_version FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE users
            SET name = ?, email = COALESCE(?, email), provider = 'github', provider_user_id = ?
            WHERE user_id = ?
            """,
            (name, email, str(github_id), user_id),
        )
        conn.commit()
        tv = int(existing["token_version"] or 0)
        return AuthUser(user_id=user_id, email=email, name=name, provider="github", token_version=tv)

    # If the email already exists for a local account, link the GitHub identity to that user
    # instead of failing the UNIQUE(email) constraint.
    if email:
        by_email = conn.execute(
            "SELECT user_id, email, name, provider, token_version FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        if by_email:
            existing_user_id = str(by_email["user_id"])
            conn.execute(
                """
                UPDATE users
                SET name = ?, provider_user_id = ?
                WHERE user_id = ?
                """,
                (name, str(github_id), existing_user_id),
            )
            conn.commit()
            tv = int(by_email["token_version"] or 0)
            # Keep the original user_id so existing email/password login still works.
            return AuthUser(
                user_id=existing_user_id,
                email=email,
                name=name,
                provider="github",
                token_version=tv,
            )

    created_at = _now_utc().isoformat()
    conn.execute(
        """
        INSERT INTO users (user_id, email, name, provider, provider_user_id, token_version, created_at)
        VALUES (?, ?, ?, 'github', ?, 0, ?)
        """,
        (user_id, email, name, str(github_id), created_at),
    )
    conn.commit()
    return AuthUser(user_id=user_id, email=email, name=name, provider="github", token_version=0)


def build_oauth_state(
    *,
    jwt_secret: str,
    return_to: str,
) -> str:
    return _signed_state(
        jwt_secret,
        {"nonce": secrets.token_urlsafe(16), "return_to": return_to, "ts": int(_now_utc().timestamp())},
    )


def parse_oauth_state(*, jwt_secret: str, state: str) -> dict[str, Any]:
    data = _verify_state(jwt_secret, state)
    ts = int(data.get("ts") or 0)
    if ts <= 0:
        raise PermissionError("Invalid OAuth state.")
    if abs(int(_now_utc().timestamp()) - ts) > 600:
        raise PermissionError("Expired OAuth state.")
    return data
