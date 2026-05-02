"""
Academy data layer: PostgreSQL (Supabase-compatible) or local JSON files.

Set **DATABASE_URL** (or **RG_DATABASE_URL** / **SUPABASE_DB_URL**) in the environment
or in **`.streamlit/secrets.toml`** to use Postgres (Supabase “connection string” / pooler URL).
Data lives in table `rg_json_documents` (one row per collection), so deploys / git
never overwrite your database — only app code changes.

Local JSON fallback keeps `RG_DATA_DIR` (default `rg_data/`) behaviour when no URL is set.

For **local** runs, create a **`.env`** file next to this module (project root). It is loaded automatically
if `python-dotenv` is installed. Put `DATABASE_URL` there (and optional `SUPABASE_URL` / `SUPABASE_KEY`
for future Supabase client features — the dashboard still uses Postgres via `DATABASE_URL` today).

Bootstrap (CLI has no Streamlit secrets — pass URL explicitly or set env):
  PowerShell:  $env:DATABASE_URL="postgresql://..."; python -m rg_datastore --bootstrap
  Or:        python -m rg_datastore --bootstrap --database-url "postgresql://..."
"""
from __future__ import annotations

import argparse
import json
import os
import socket
from typing import Any
from urllib.parse import ParseResult, parse_qs, unquote, urlparse

import rg_security

_ROOT = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(_ROOT, ".env"))
    except ImportError:
        pass


_load_dotenv()

DATA_DIR = os.environ.get("RG_DATA_DIR", "rg_data")



def ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _path(name: str) -> str:
    return os.path.join(DATA_DIR, f"{name}.json")


def database_url() -> str | None:
    for key in ("DATABASE_URL", "RG_DATABASE_URL", "SUPABASE_DB_URL"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    try:
        import streamlit as st

        sec = st.secrets
        for key in ("DATABASE_URL", "RG_DATABASE_URL", "SUPABASE_DB_URL"):
            if key in sec and str(sec[key]).strip():
                return str(sec[key]).strip()
    except Exception:
        pass
    return None


def _load_file(name: str) -> Any:
    ensure_data_dir()
    if not os.path.exists(_path(name)):
        return [] if name == "feedback" else {}
    with open(_path(name), encoding="utf-8") as f:
        data = json.load(f)
    if name == "feedback" and not isinstance(data, list):
        return []
    return data


def _save_file(name: str, data: Any) -> None:
    ensure_data_dir()
    rg_security.atomic_write_json(_path(name), data, default=str)


def _assert_real_database_url(parsed: ParseResult) -> None:
    """Fail fast when someone pastes documentation placeholders instead of a real Supabase URI."""
    host = (parsed.hostname or "").strip().rstrip(".")
    if not host or host.upper() == "HOST" or host == "...":
        raise RuntimeError(
            'Hostname is missing, is "...", or is literally "HOST". '
            "Use a full URI from Supabase → **Project Settings** → **Database** "
            "(host looks like `db.<project-ref>.supabase.co`). "
            "In PowerShell paste the URL as one line inside **single quotes**."
        )
    if ".." in host:
        raise RuntimeError(f"Invalid hostname {host!r} (contains `..`). Check the URL was not truncated.")
    if "." not in host:
        raise RuntimeError(f"Invalid hostname {host!r} (expected a DNS name with a dot, e.g. db.xxx.supabase.co).")
    user = (parsed.username or "").strip()
    pw = parsed.password or ""
    if user.upper() == "USER" or pw == "ENCODED_PASSWORD":
        raise RuntimeError(
            'URL still contains placeholder **USER** or **ENCODED_PASSWORD**. '
            "Use the real database user (usually `postgres`) and your actual password "
            "(URL-encode characters like `[` `]` `@` `#` in the password part)."
        )


def _pg_connect_params(url: str) -> dict[str, Any]:
    """
    Build libpq keyword args from the URI. Avoids some Windows/psycopg URI→DNS edge cases
    by passing host/port/user/password explicitly.
    """
    u = (url or "").strip().replace("\ufeff", "").replace("\r", "").replace("\n", "")
    parsed = urlparse(u)
    if parsed.scheme not in ("postgres", "postgresql"):
        raise RuntimeError(f"Unsupported URL scheme {parsed.scheme!r}; use postgresql://...")
    _assert_real_database_url(parsed)
    host = (parsed.hostname or "").strip().rstrip(".")
    port = parsed.port or 5432
    path = (parsed.path or "").strip("/")
    dbname = path or "postgres"
    user = unquote(parsed.username) if parsed.username else "postgres"
    password = unquote(parsed.password) if parsed.password is not None else ""
    q = parse_qs(parsed.query or "")
    sslmode_vals = q.get("sslmode") or []
    h = host.lower()
    sslmode = sslmode_vals[0] if sslmode_vals else (
        "require" if "supabase.co" in h or "pooler.supabase.com" in h else "prefer"
    )
    return {
        "host": host,
        "port": port,
        "dbname": dbname,
        "user": user,
        "password": password,
        "sslmode": sslmode,
        "connect_timeout": 20,
    }


def _pg_connect():
    import psycopg

    url = (database_url() or "").strip()
    if not url:
        raise RuntimeError("Database URL is empty.")
    params = _pg_connect_params(url)
    try:
        # Transaction pooler (port 6543) does not support prepared statements the same way.
        return psycopg.connect(**params, prepare_threshold=None)
    except psycopg.OperationalError as e:
        err = str(e).lower()
        if "getaddrinfo" in err or "resolve" in err or "11001" in str(e):
            raise RuntimeError(
                "Could not resolve the database host (DNS / network). Supabase **direct** URLs "
                "(`db.<ref>.supabase.co`) are often **IPv6-only**; on IPv4-only networks they fail with "
                "getaddrinfo / Windows 11001.\n\n"
                "Fix: Supabase → **Connect** → **Session pooler** and copy the full URI. "
                "It uses user **`postgres.<project-ref>`** and host **`aws-0-` or `aws-1-`<region>.pooler.supabase.com`** "
                "(not `db.<ref>.supabase.co`). URL-encode special characters in the password (`@` → `%40`). "
                "Add `?sslmode=require` if missing."
            ) from e
        if "tenant" in err and "not found" in err:
            raise RuntimeError(
                "Pooler rejected the username/host combination (tenant/user not found). "
                "Copy the **Session** or **Transaction** pooler URI from Supabase → **Connect** exactly — "
                "especially the pooler hostname (**`aws-0-...` vs `aws-1-...`** varies by project). "
                "Username must be **`postgres.<your-project-ref>`** for the shared pooler on `*.pooler.supabase.com`."
            ) from e
        raise
    except (UnicodeError, socket.gaierror, OSError) as e:
        raise RuntimeError(
            f"Could not open a database connection ({type(e).__name__}) to host {params['host']!r}. "
            "Re-copy the URI from Supabase; in PowerShell use single quotes around the URL if `?` causes issues: "
            '''--database-url 'postgresql://...?sslmode=require' '''
        ) from e


def _ensure_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS rg_json_documents (
            collection TEXT PRIMARY KEY,
            body JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS rg_json_documents_updated_at_idx
        ON rg_json_documents (updated_at DESC)
        """
    )


def _load_pg(name: str) -> Any:
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            _ensure_table(cur)
            cur.execute(
                "SELECT body FROM rg_json_documents WHERE collection = %s",
                (name,),
            )
            row = cur.fetchone()
    if row is None:
        return [] if name == "feedback" else {}
    body = row[0]
    if name == "feedback" and not isinstance(body, list):
        return []
    return body


def _save_pg(name: str, data: Any) -> None:
    import psycopg
    from psycopg.types.json import Json

    payload = json.loads(json.dumps(data, default=str))
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            _ensure_table(cur)
            cur.execute(
                """
                INSERT INTO rg_json_documents (collection, body, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (collection) DO UPDATE SET
                    body = EXCLUDED.body,
                    updated_at = NOW()
                """,
                (name, Json(payload)),
            )
        conn.commit()


def load(name: str) -> Any:
    if database_url():
        try:
            return _load_pg(name)
        except ModuleNotFoundError as e:
            raise RuntimeError(
                "PostgreSQL URL is set but psycopg is not installed. "
                "Run: pip install 'psycopg[binary]>=3.1'"
            ) from e
    return _load_file(name)


def save(name: str, data: Any) -> None:
    if database_url():
        try:
            _save_pg(name, data)
        except ModuleNotFoundError as e:
            raise RuntimeError(
                "PostgreSQL URL is set but psycopg is not installed. "
                "Run: pip install 'psycopg[binary]>=3.1'"
            ) from e
    else:
        _save_file(name, data)


def bootstrap_from_json_files() -> int:
    """
    Copy each `rg_data/*.json` collection into Postgres if that row is missing.
    Returns number of rows inserted/updated.
    """
    if not database_url():
        raise RuntimeError(
            "No database URL. For local bootstrap, either:\n"
            "  • PowerShell:  $env:DATABASE_URL='postgresql://...'; python -m rg_datastore --bootstrap\n"
            "  • Or pass:     python -m rg_datastore --bootstrap --database-url \"postgresql://...\"\n"
            "(Streamlit Cloud secrets are only available inside `streamlit run`, not in this CLI.)"
        )
    ensure_data_dir()
    from psycopg.types.json import Json

    n = 0
    for fname in os.listdir(DATA_DIR):
        if not fname.endswith(".json"):
            continue
        name = fname[:-5]
        if not os.path.isfile(_path(name)):
            continue
        with open(_path(name), encoding="utf-8") as f:
            data = json.load(f)
        if name == "feedback" and not isinstance(data, list):
            data = []
        payload = json.loads(json.dumps(data, default=str))
        with _pg_connect() as conn:
            with conn.cursor() as cur:
                _ensure_table(cur)
                cur.execute(
                    "SELECT 1 FROM rg_json_documents WHERE collection = %s",
                    (name,),
                )
                if cur.fetchone() is None:
                    cur.execute(
                        """
                        INSERT INTO rg_json_documents (collection, body, updated_at)
                        VALUES (%s, %s, NOW())
                        """,
                        (name, Json(payload)),
                    )
                    n += 1
            conn.commit()
    return n


def main() -> None:
    p = argparse.ArgumentParser(description="RallyGully datastore utilities")
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="Copy JSON files from RG_DATA_DIR into Postgres when rows are missing",
    )
    p.add_argument(
        "--database-url",
        metavar="URL",
        help="Postgres connection string for this run (always overrides DATABASE_URL when passed)",
    )
    args = p.parse_args()
    if args.database_url:
        # CLI must win over a stale session $env:DATABASE_URL (e.g. "..." from earlier tests).
        u = args.database_url.strip().strip("'\"").replace("\ufeff", "")
        os.environ["DATABASE_URL"] = u
    if args.bootstrap:
        inserted = bootstrap_from_json_files()
        print(f"Bootstrap finished. New collections written: {inserted}")


if __name__ == "__main__":
    main()
