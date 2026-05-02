# RallyGully Academy Dashboard

Streamlit app for venues, batches, coaches, athletes, sessions, and analytics.

## First-time setup (Windows)

1. **Clone** the repo and open the folder in PowerShell.
2. **Local secrets** are in `.env` (already gitignored). It should define:
   - `DATABASE_URL` — Supabase Postgres (use **transaction pooler** on port **6543** if direct `5432` fails on your network).
   - `SUPABASE_URL` and `SUPABASE_KEY` — from Supabase project settings (for optional `supabase-py` use).
3. **Install & run** (double-click or run in PowerShell):

   ```powershell
   .\run_app.ps1
   ```

4. **Copy JSON data into Postgres once** (if you use Postgres and have files under `rg_data/`):

   ```powershell
   .\migrate_to_db.ps1
   ```

## Streamlit Community Cloud

- Add the same variables in **App settings → Secrets** (see `.streamlit/secrets.toml.example`).
- Do **not** commit real secrets; `.env` and `secrets.toml` are gitignored.

## Data storage

- With **`DATABASE_URL` set**: data lives in Supabase Postgres (table `rg_json_documents`).
- **Without it**: JSON files under `rg_data/` (ignored by git except `seeded.json`).
