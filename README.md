# Diet Project – Phase 3 (Performance + Security)

This repo implements **Phase 3** requirements:

- **Caching/performance:** data cleaning + insight calculations run **only when `All_Diets.csv` changes** (Blob Trigger).
- **Secure dashboard:** real **email/password registration + login** (hashed passwords), plus **GitHub OAuth** login.
- **Interactive data API:** `/api/recipes` supports **diet filter**, **keyword search**, and **pagination**.

## Architecture

**Backend (Azure Functions, Python)** – `backend/`

- **Blob Trigger**: watches `DIETS_CONTAINER/DIETS_BLOB` and on update:
  - cleans the CSV once
  - writes cleaned CSV to `DIETS_CLEAN_CONTAINER/DIETS_CLEAN_BLOB`
  - computes dashboard aggregates once and writes JSON to `DIETS_CACHE_CONTAINER`
- **HTTP API (protected by JWT)**:
  - `GET /api/insights` reads precomputed `insights.json` only
  - `GET /api/recipes` reads cleaned CSV and performs filter/search/pagination
  - `GET /api/clusters` reads precomputed `clusters.json` only
- **Users DB**: Azure **Table Storage** (`USERS_TABLE_NAME`) stores user profiles and password hashes.

Security notes:

- **Passwords** are stored as **bcrypt hashes** (never plain text).
- In Azure, **Storage (Blob/Table) is encrypted at rest by the platform** (your instructor may want you to mention this explicitly in the presentation/demo).

**Frontend (static dashboard + optional Flask host)** – `frontend/`

- `frontend/dashboard/index.html` is the dashboard UI.
- `frontend/app.py` can serve the UI locally and provides `/config.js` to set `window.BACKEND_URL`.

## Environment variables (required)

Copy `/Users/mistym0de/diet-project/.env.example` to `.env` for local work (optional), and set the same variables in Azure App Settings for the Function App.

Backend (Functions):

- `AzureWebJobsStorage` (or `AZURE_STORAGE_CONNECTION_STRING`)
- `DIETS_CONTAINER`, `DIETS_BLOB`
- `DIETS_CLEAN_CONTAINER`, `DIETS_CLEAN_BLOB`
- `DIETS_CACHE_CONTAINER`, `INSIGHTS_BLOB`, `CLUSTERS_BLOB`
- `USERS_TABLE_NAME` (must be alphanumeric; no hyphens)
- `JWT_SECRET`, `JWT_ISSUER`, `JWT_AUDIENCE`, `JWT_TTL_SECONDS`
- `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` (for OAuth)

Frontend (optional Flask host):

- `BACKEND_URL` (base URL of your Function App, e.g. `http://localhost:7071`)

## Run locally (end-to-end)

### 1) Start Azurite (Blob + Table)

Use whichever you prefer:

- **No Docker needed (recommended):** start Azurite via `npx`:
  - `bash backend/scripts/start_azurite.sh`
- Docker: run Azurite locally (Blob/Queue/Table)
- Or install Azurite via npm and run it directly

Your Functions `local.settings.json` should contain:

- `AzureWebJobsStorage=UseDevelopmentStorage=true`
- a non-empty `JWT_SECRET`

### 2) Backend (Azure Functions)

From `backend/`:

1. Create `backend/local.settings.json` from the example (auto-generates `JWT_SECRET`):
   - `python scripts/create_local_settings.py`
2. Install Python deps:
   - `pip install -r requirements.txt`
3. Initialize containers + users table:
   - `python scripts/init_storage.py`
4. Start Functions host:
   - `func start`
5. Upload the CSV to trigger cleaning + precompute:
   - `python scripts/upload_all_diets.py`

Wait for the Functions logs to show that the Blob Trigger ran and wrote the cache blobs.

### 3) Frontend (optional local host)

From `frontend/`:

1. Create `.env` from `frontend/.env.example` and set `BACKEND_URL=http://localhost:7071`
2. Install deps:
   - `pip install -r requirements.txt`
3. Run:
   - `python app.py`
4. Open:
   - `http://localhost:5000`

## Deploy to Azure

### 1) Storage account

Create an Azure Storage account (Blob + Table).

Create containers:

- `datasets`
- `datasets-clean`
- `datasets-cache`

### 2) Function App

Create a Python Azure Function App and deploy `backend/`.

In Function App → Configuration → Application settings, set:

- `AzureWebJobsStorage` = your Storage connection string
- `JWT_SECRET` = long random secret
- the `DIETS_*` and `USERS_TABLE_NAME` values (defaults are fine)
- `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`

Upload `All_Diets.csv` to `datasets/All_Diets.csv` to trigger the cache build.

### 3) GitHub OAuth app

Create a GitHub OAuth App:

- **Authorization callback URL**: `https://<your-function-app>.azurewebsites.net/api/oauth/github/callback`
- Copy `Client ID` and `Client Secret` to the Function App settings.

### 4) Static dashboard hosting

Host `frontend/dashboard/` via Azure Static Web Apps (or any static host).

You must provide `window.BACKEND_URL` for the UI. Options:

- If you use the Flask host: set `BACKEND_URL` and use `/config.js`
- If you host statically: copy `frontend/dashboard/config.example.js` to `frontend/dashboard/config.js` and set:

```js
window.BACKEND_URL = "https://<your-function-app>.azurewebsites.net";
```

## Presentation demo flow (meets rubric)

1. **Show caches are built only when CSV changes**
   - Upload version 1 of `All_Diets.csv` to `datasets/All_Diets.csv`
   - Show Functions logs: Blob Trigger ran once and wrote:
     - cleaned CSV blob
     - insights/clusters JSON blobs
   - Refresh dashboard multiple times: `/api/insights` is fast and reads cached JSON only
2. **Update CSV and show recompute happens once**
   - Upload version 2 (a small edit) to the same blob path
   - Show Blob Trigger runs once again and updates cache timestamps
3. **Auth**
   - Register with email/password
   - Log out, log in again
   - Sign in with GitHub OAuth
4. **Data interaction + pagination**
   - Use search keyword + diet filter
   - Click next/previous page to show stable pagination

## Sample curl commands

Replace `BASE` with your Function App base URL.

Register:

```bash
BASE=http://localhost:7071
curl -sS -X POST "$BASE/api/auth/register" -H "Content-Type: application/json" \
  -d '{"name":"Alice","email":"alice@example.com","password":"password123"}'
```

Login:

```bash
TOKEN=$(curl -sS -X POST "$BASE/api/auth/login" -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"password123"}' | python -c 'import sys,json; print(json.load(sys.stdin)["token"])')
```

Insights:

```bash
curl -sS "$BASE/api/insights" -H "Authorization: Bearer $TOKEN"
```

Recipes (page/search/filter):

```bash
curl -sS "$BASE/api/recipes?page=1&pageSize=10&diet=Keto&search=chicken" \
  -H "Authorization: Bearer $TOKEN"
```

Logout (revokes token via token_version):

```bash
curl -sS -X POST "$BASE/api/auth/logout" -H "Authorization: Bearer $TOKEN"
```

## Test checklist

- Upload `All_Diets.csv` once → Blob Trigger runs once; cache blobs exist
- Repeated `GET /api/insights` does **not** re-clean CSV
- `/api/recipes` correctly filters by `diet`, searches by keyword, and paginates stably
- Register → password hash stored in Table Storage (no plain password)
- Login issues JWT; protected endpoints reject missing/invalid token
- GitHub OAuth login redirects back to dashboard and user name is shown
- Logout revokes token (old token rejected)
