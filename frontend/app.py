import json
import os
import urllib.error
import urllib.request

from flask import Flask, Response, jsonify, send_from_directory
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="dashboard", static_url_path="")

@app.get("/health")
def health():
    return "ok", 200


@app.get("/diag")
def diag():
    index_path = os.path.join(app.root_path, "dashboard", "index.html")
    has_index = os.path.exists(index_path)
    backend_url = os.getenv("BACKEND_URL", "")
    return {
        "has_index_html": has_index,
        "backend_url_configured": bool(backend_url),
    }, 200


@app.get("/config.js")
def config():
    backend_url = os.getenv("BACKEND_URL", "")
    body = f"window.BACKEND_URL = {json.dumps(backend_url)};\\n"
    resp = Response(body, mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


@app.get("/api/results")
def api_results():
    backend_url = os.getenv("BACKEND_URL", "")
    if not backend_url:
        return jsonify(
            error="Missing BACKEND_URL. Set it in Azure App Service → Configuration → Application settings."
        ), 500

    req = urllib.request.Request(
        backend_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "diet-dashboard-frontend/1.0",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            content_type = resp.headers.get("Content-Type", "application/json")
            body = resp.read()
            out = Response(body, status=resp.status, mimetype=content_type)
            out.headers["Cache-Control"] = "no-store, max-age=0"
            return out
    except urllib.error.HTTPError as e:
        body = e.read() if hasattr(e, "read") else str(e).encode("utf-8")
        return Response(body, status=e.code, mimetype="text/plain")
    except Exception as e:
        return jsonify(error=f"Backend request failed: {e}"), 502


@app.get("/")
def index():
    return send_from_directory("dashboard", "index.html")


@app.get("/<path:path>")
def static_files(path: str):
    return send_from_directory("dashboard", path)
