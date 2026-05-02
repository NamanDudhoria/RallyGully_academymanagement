"""
Optional Supabase client (`pip install supabase`).

Set **SUPABASE_URL** and **SUPABASE_KEY** (or **SUPABASE_ANON_KEY**) in `.env` or the environment.
Academy **data** still flows through **rg_datastore** + **DATABASE_URL** (Postgres); this client is for
Auth / Storage / Realtime when you add those features.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from supabase import Client


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        root = os.path.dirname(os.path.abspath(__file__))
        load_dotenv(os.path.join(root, ".env"))
    except ImportError:
        pass


def supabase_client() -> "Client":
    _load_dotenv()
    from supabase import create_client

    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (
        (os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY") or "").strip()
    )
    if not url or not key:
        raise RuntimeError(
            "Missing SUPABASE_URL or SUPABASE_KEY (or SUPABASE_ANON_KEY). "
            "Add them to .env (local) or Streamlit secrets / host env."
        )
    return create_client(url, key)
