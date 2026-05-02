import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
import html
import json
import os
import random

import rg_security

# ─────────────────────────────────────────────
#  RallyGully brand (aligned with rallygully.com + wordmark)
# ─────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
_FAVICON = os.path.join(_ROOT, "favicon.ico")
RG_PURPLE = "#5D2689"
RG_PURPLE_DEEP = "#3d1a5c"
RG_ORANGE = "#F39221"
RG_ORANGE_SOFT = "#fff4e8"
RG_TEXT = "#000000"
RG_MUTED = "#333333"
RG_BG = "#faf8fc"
RG_CARD = "#ffffff"
RG_BORDER = "#e8e0f0"
RG_PURPLE_SOFT = "#ede7f4"
# Default admin login when no secrets / env / config (override in production)
DEFAULT_ADMIN_PASSWORD = "RallyGully_123"

# Batch time options (Academy enrollment form)
OTHER_BATCH_ID = "B006"
BATCH_TIME_PRESETS = [
    {"batch_id": "B001", "label": "Monday – Wednesday – Friday, 5 PM – 6 PM", "program": "3-Day"},
    {"batch_id": "B002", "label": "Monday – Wednesday – Friday, 6 PM – 7 PM", "program": "3-Day"},
    {"batch_id": "B003", "label": "Tuesday – Thursday – Saturday, 5 PM – 6 PM", "program": "3-Day"},
    {"batch_id": "B004", "label": "Tuesday – Thursday – Saturday, 6 PM – 7 PM", "program": "3-Day"},
    {"batch_id": "B005", "label": "M–T–W–Th–F, 6–7 PM (5-day batch)", "program": "5-Day"},
]


def _presets_for_venue(venue_id, batches_dict):
    """Batch-time slots that exist at this venue (venue ↔ batch ↔ student)."""
    out = []
    for p in BATCH_TIME_PRESETS:
        b = batches_dict.get(p["batch_id"]) or {}
        if b.get("venue_id") == venue_id:
            out.append(p)
    return out


def _coaches_at_venue(venue_id, coaches_dict):
    return [cid for cid, c in coaches_dict.items() if venue_id in c.get("venue_ids", [])]


def _venue_option_label(venues_dict, vid):
    v = venues_dict.get(vid) or {}
    return f"{v.get('name', vid)} — {v.get('city', '')}"

# ─────────────────────────────────────────────
#  DATA LAYER  (flat JSON files, no DB needed)
# ─────────────────────────────────────────────
DATA_DIR = os.environ.get("RG_DATA_DIR", "rg_data")
os.makedirs(DATA_DIR, exist_ok=True)

def _path(name): return os.path.join(DATA_DIR, f"{name}.json")

def _esc(x) -> str:
    """Escape user-controlled text embedded in st.markdown HTML."""
    return html.escape(str(x or ""), quote=True)


def load(name):
    if not os.path.exists(_path(name)):
        return [] if name == "feedback" else {}
    with open(_path(name), encoding="utf-8") as f:
        data = json.load(f)
    if name == "feedback" and not isinstance(data, list):
        return []
    return data

def save(name, data):
    rg_security.atomic_write_json(_path(name), data, default=str)

def _migrate_sessions_structure():
    raw = load("sessions")
    if isinstance(raw, list):
        save("sessions", {row["session_id"]: row for row in raw})

_migrate_sessions_structure()


def _ensure_venues_and_batch_links():
    """Create venues if missing; link batches/athletes/coaches to venue_id."""
    venues = load("venues")
    if not venues:
        venues = {
            "V001": {"name": "South Court", "city": "Academy Hub", "address": "Sector A – main campus", "active": True},
            "V002": {"name": "North Court", "city": "Academy Hub", "address": "Sector B – satellite", "active": True},
        }
        save("venues", venues)
    batches = load("batches")
    coaches = load("coaches")
    athletes = load("athletes")
    changed = False
    name_to_id = {v["name"].strip().lower(): k for k, v in venues.items()}
    for bk, bv in batches.items():
        if not bv.get("venue_id"):
            guess = name_to_id.get((bv.get("venue") or "").strip().lower()) or "V001"
            bv["venue_id"] = guess
            changed = True
        vid = bv.get("venue_id")
        if vid in venues and bv.get("venue") != venues[vid]["name"]:
            bv["venue"] = venues[vid]["name"]
            changed = True
    for cid, c in coaches.items():
        if not c.get("venue_ids"):
            vset = []
            for bid in c.get("batches", []):
                if bid in batches and batches[bid].get("venue_id"):
                    vset.append(batches[bid]["venue_id"])
            c["venue_ids"] = list(dict.fromkeys(vset)) or ["V001"]
            changed = True
    for aid, a in athletes.items():
        bid = a.get("batch")
        if bid and bid in batches and not a.get("venue_id"):
            a["venue_id"] = batches[bid].get("venue_id", "V001")
            changed = True
    if changed:
        save("batches", batches)
        save("coaches", coaches)
        save("athletes", athletes)


def _admin_auth_context():
    """
    Returns (material, source) for admin login.
    material: bcrypt hash or plaintext (never logged).
    source: 'secrets' | 'env' | 'file' | 'default' | 'none'
    """
    try:
        sec = st.secrets
        if sec is not None and "ADMIN_PASSWORD" in sec:
            v = str(sec["ADMIN_PASSWORD"]).strip()
            if v:
                return v, "secrets"
    except (FileNotFoundError, KeyError, AttributeError, RuntimeError, Exception):
        pass
    envp = os.environ.get("RG_ADMIN_PASSWORD", "").strip()
    if envp:
        return envp, "env"
    cfg = load("config")
    file_pw = (cfg.get("admin_password") or "").strip()
    if file_pw:
        return file_pw, "file"
    if rg_security.is_production():
        return None, "none"
    return DEFAULT_ADMIN_PASSWORD, "default"

# ─── seed demo data ──────────────────────────
def _seed():
    if load("seeded").get("done"):
        return
    _pw_ath = rg_security.hash_password("1234")
    _pw_co = rg_security.hash_password("coach")
    venues = {
        "V001": {"name": "South Court", "city": "Academy Hub", "address": "Sector A – main campus", "active": True},
        "V002": {"name": "North Court", "city": "Academy Hub", "address": "Sector B – satellite", "active": True},
    }
    athletes = {
        "A001": {"name": "Arjun Mehta", "email": "arjun@rg.in", "password": _pw_ath,
                 "batch": "B001", "program": "3-Day", "week": 3, "join_date": "2025-04-01",
                 "sessions_attended": 8, "venue_id": "V001", "phone": "+91 90000 10001",
                 "experience": "6–24 months", "emergency_contact": "Parent Mehta +91 90000 20001"},
        "A002": {"name": "Priya Sharma", "email": "priya@rg.in", "password": _pw_ath,
                 "batch": "B001", "program": "3-Day", "week": 3, "join_date": "2025-04-01",
                 "sessions_attended": 9, "venue_id": "V001", "phone": "+91 90000 10002",
                 "experience": "New to pickleball", "emergency_contact": "Parent Sharma +91 90000 20002"},
        "A003": {"name": "Rohan Das",   "email": "rohan@rg.in", "password": _pw_ath,
                 "batch": "B005", "program": "5-Day", "week": 2, "join_date": "2025-04-15",
                 "sessions_attended": 10, "venue_id": "V001", "phone": "+91 90000 10003",
                 "experience": "< 6 months", "emergency_contact": "R. Das +91 90000 20003"},
        "A004": {"name": "Sneha Iyer",  "email": "sneha@rg.in", "password": _pw_ath,
                 "batch": "B005", "program": "5-Day", "week": 2, "join_date": "2025-04-15",
                 "sessions_attended": 8, "venue_id": "V001", "phone": "+91 90000 10004",
                 "experience": "2+ years / competitive", "emergency_contact": "S. Iyer +91 90000 20004"},
    }
    coaches = {
        "C001": {"name": "Vikram Nair",   "email": "vikram@rg.in", "password": _pw_co,
                 "batches": ["B001", "B003", "B005", "B006"], "venue_ids": ["V001"],
                 "speciality": "Beginner Foundations"},
        "C002": {"name": "Anjali Rao",    "email": "anjali@rg.in", "password": _pw_co,
                 "batches": ["B002", "B004"], "venue_ids": ["V002"],
                 "speciality": "Beginner Foundations"},
    }
    batches = {
        "B001": {"name": "MWF · 5:00–6:00 PM", "coach_id": "C001",
                 "program": "3-Day", "start_date": "2025-04-01",
                 "days": "Mon / Wed / Fri", "time": "5:00 PM – 6:00 PM", "venue": "South Court",
                 "venue_id": "V001", "athlete_ids": ["A001", "A002"], "status": "Active"},
        "B002": {"name": "MWF · 6:00–7:00 PM", "coach_id": "C002",
                 "program": "3-Day", "start_date": "2025-04-01",
                 "days": "Mon / Wed / Fri", "time": "6:00 PM – 7:00 PM", "venue": "North Court",
                 "venue_id": "V002", "athlete_ids": [], "status": "Active"},
        "B003": {"name": "Tue–Thu–Sat · 5:00–6:00 PM", "coach_id": "C001",
                 "program": "3-Day", "start_date": "2025-04-01",
                 "days": "Tue / Thu / Sat", "time": "5:00 PM – 6:00 PM", "venue": "South Court",
                 "venue_id": "V001", "athlete_ids": [], "status": "Active"},
        "B004": {"name": "Tue–Thu–Sat · 6:00–7:00 PM", "coach_id": "C002",
                 "program": "3-Day", "start_date": "2025-04-01",
                 "days": "Tue / Thu / Sat", "time": "6:00 PM – 7:00 PM", "venue": "North Court",
                 "venue_id": "V002", "athlete_ids": [], "status": "Active"},
        "B005": {"name": "Mon–Fri · 6:00–7:00 PM (5-day)", "coach_id": "C001",
                 "program": "5-Day", "start_date": "2025-04-15",
                 "days": "Mon – Fri", "time": "6:00 PM – 7:00 PM", "venue": "South Court",
                 "venue_id": "V001", "athlete_ids": ["A003", "A004"], "status": "Active"},
        "B006": {"name": "Custom / Other (admin assigns)", "coach_id": "C001",
                 "program": "3-Day", "start_date": "2025-04-01",
                 "days": "TBD", "time": "TBD", "venue": "South Court",
                 "venue_id": "V001", "athlete_ids": [], "status": "Active"},
    }
    # skill scores per athlete (week → skill → score 1-10)
    perf = {
        "A001": {"w1": {"grip":7,"serve":6,"forehand":7,"backhand":6,"dink":4,"movement":7},
                 "w2": {"grip":8,"serve":7,"forehand":8,"backhand":7,"dink":6,"movement":8},
                 "w3": {"grip":9,"serve":8,"forehand":8,"backhand":8,"dink":7,"movement":8}},
        "A002": {"w1": {"grip":6,"serve":5,"forehand":6,"backhand":5,"dink":5,"movement":6},
                 "w2": {"grip":7,"serve":7,"forehand":7,"backhand":6,"dink":6,"movement":7},
                 "w3": {"grip":8,"serve":8,"forehand":8,"backhand":7,"dink":8,"movement":8}},
        "A003": {"w1": {"grip":8,"serve":7,"forehand":7,"backhand":7,"dink":5,"movement":7},
                 "w2": {"grip":9,"serve":8,"forehand":8,"backhand":8,"dink":7,"movement":8}},
        "A004": {"w1": {"grip":7,"serve":6,"forehand":7,"backhand":6,"dink":6,"movement":6},
                 "w2": {"grip":8,"serve":7,"forehand":7,"backhand":7,"dink":7,"movement":7}},
    }
    # coach feedback from athletes (anonymous)
    feedback = [
        {"athlete_id":"A001","coach_id":"C001","week":1,"date":"2025-04-07",
         "session_energy":9,"explanation_clarity":8,"drill_quality":8,
         "felt_challenged":9,"comment":"Loved the competitive drills. Felt like a real session."},
        {"athlete_id":"A002","coach_id":"C001","week":1,"date":"2025-04-07",
         "session_energy":8,"explanation_clarity":9,"drill_quality":8,
         "felt_challenged":7,"comment":"Great energy. Could explain the dink rules more clearly."},
        {"athlete_id":"A001","coach_id":"C001","week":2,"date":"2025-04-14",
         "session_energy":9,"explanation_clarity":9,"drill_quality":9,
         "felt_challenged":8,"comment":"The dink battles were intense. Really liked the competitive format."},
        {"athlete_id":"A003","coach_id":"C001","week":1,"date":"2025-04-21",
         "session_energy":8,"explanation_clarity":8,"drill_quality":9,
         "felt_challenged":8,"comment":"5 days felt a lot but we adapted. Great coach."},
        {"athlete_id":"A004","coach_id":"C001","week":1,"date":"2025-04-21",
         "session_energy":9,"explanation_clarity":8,"drill_quality":8,
         "felt_challenged":9,"comment":"Loved the fitness circuits at the end."},
    ]
    # session logs (coach fills after each session)
    sessions = [
        {"session_id":"S001","batch_id":"B001","coach_id":"C001","date":"2025-04-02",
         "week":1,"session_num":1,"program_session":"Week 1 – Session 1",
         "focus":"Court orientation, paddle grip, ready position",
         "drills_run":"Bounce-and-catch, court boundary games",
         "fitness_done":"Lateral shuffle relay",
         "game_block_done":True,"sweat":True,"competitive_moment":True,
         "coach_notes":"Group arrived nervous. Energy lifted after court tag.","attendance":["A001","A002"]},
        {"session_id":"S002","batch_id":"B001","coach_id":"C001","date":"2025-04-04",
         "week":1,"session_num":2,"program_session":"Week 1 – Session 2",
         "focus":"Forehand + backhand groundstrokes, two-bounce rule",
         "drills_run":"Alternating forehand/backhand feed drills",
         "fitness_done":"Sprint to baseline race format",
         "game_block_done":True,"sweat":True,"competitive_moment":True,
         "coach_notes":"A001 showing natural forehand. A002 needs backhand work.","attendance":["A001","A002"]},
        {"session_id":"S003","batch_id":"B005","coach_id":"C001","date":"2025-04-16",
         "week":1,"session_num":1,"program_session":"Week 1 – Day 1",
         "focus":"Court orientation, paddle grip, ready position",
         "drills_run":"Bounce-and-catch rallies, shadow swings",
         "fitness_done":"Court tag warmup",
         "game_block_done":True,"sweat":True,"competitive_moment":True,
         "coach_notes":"Larger group than expected. Split into two lines.","attendance":["A003","A004"]},
    ]
    save("venues", venues)
    save("athletes", athletes)
    save("coaches", coaches)
    save("batches", batches)
    save("performance", perf)
    save("feedback", feedback)
    save("sessions", {s["session_id"]: s for s in sessions})
    save("seeded", {"done": True})

_seed()
_ensure_venues_and_batch_links()

# ─────────────────────────────────────────────
#  CURRICULUM DATA
# ─────────────────────────────────────────────
CURRICULUM_3DAY = {
    1: [
        {"session": 1, "focus": "Court orientation, paddle grip, ready position",
         "key_drills": "Bounce-and-catch rallies, shadow paddle swings, court boundary games",
         "fitness": "Lateral shuffle relay, court tag warmup"},
        {"session": 2, "focus": "Forehand + backhand groundstrokes, two-bounce rule",
         "key_drills": "Alternating forehand/backhand feed drills, two-bounce rally games",
         "fitness": "Sprint to baseline and back – race format between pairs"},
        {"session": 3, "focus": "Serve mechanics + first full rally game",
         "key_drills": "Serve-and-move drill: serve then sprint to kitchen; serve-to-point mini-games",
         "fitness": "Serve accuracy target game + end-of-week fitness circuit"},
    ],
    2: [
        {"session": 4, "focus": "Non-volley zone rules + kitchen positioning",
         "key_drills": "Kitchen line approach drill; dink challenge: first pair to 10 consecutive dinks wins",
         "fitness": "Cone slalom sprint to kitchen; loser of dink challenge does lateral shuttles"},
        {"session": 5, "focus": "Dink mechanics + third shot introduction",
         "key_drills": "Cross-court dink rally (target 5 consecutive); serve to return to third shot drop sequence",
         "fitness": "Competitive serve-to-third-shot rally: points awarded for clean drops"},
        {"session": 6, "focus": "Movement at kitchen + game day with full kitchen rules",
         "key_drills": "Split-step and lateral reach drills; full match play with proper scoring",
         "fitness": "🏋️ FITNESS TEST: Timed court shuttles – record every player's time"},
    ],
    3: [
        {"session": 7, "focus": "Doubles positioning + return of serve mechanics",
         "key_drills": "2v2 position drills; return-wide-then-sprint-to-kitchen sequence",
         "fitness": "Competitive doubles rallies; sprint-to-kitchen race format"},
        {"session": 8, "focus": "Attacking mid-court + reset mechanics",
         "key_drills": "Speedup drill: dink-dink-drive trigger; reset drill under pressure",
         "fitness": "Reaction volley circuit: coach feeds rapid volleys, player defends 60s"},
        {"session": 9, "focus": "Full competitive match day – observed",
         "key_drills": "Doubles tournament: round-robin, proper scoring, coach observes",
         "fitness": "Endurance finisher: 3-min continuous rally – group target 50 shots"},
    ],
    4: [
        {"session": 10, "focus": "Full skill review + serve and return pressure session",
         "key_drills": "Player self-assess weakest skill; targeted 15-min drill block; serve pressure game",
         "fitness": "🏋️ FITNESS BENCHMARK: Timed shuttles – compare to Session 6"},
        {"session": 11, "focus": "Kitchen mastery under fatigue + strategy session",
         "key_drills": "Dink battle under fatigue; coach sets tactical scenarios",
         "fitness": "Stamina circuit: 4 rounds shuffle-sprint-dink, 6 minutes continuous"},
        {"session": 12, "focus": "Month-end showcase and closing ceremony",
         "key_drills": "Final tournament: full doubles round-robin, proper rally scoring",
         "fitness": "Closing ceremony: coach names specific growth for every player"},
    ],
}

CURRICULUM_5DAY = {
    1: [
        {"session": 1, "focus": "Court orientation, paddle grip, ready position",
         "key_drills": "Bounce-and-catch rallies, shadow paddle swings, court boundary games",
         "fitness": "Lateral shuffle relay, court tag warmup"},
        {"session": 2, "focus": "Forehand groundstroke introduction",
         "key_drills": "Toss-and-hit repetitions, forehand feed rally from mid-court",
         "fitness": "Sprint to baseline and back – race format between pairs"},
        {"session": 3, "focus": "Backhand groundstroke + two-bounce rule",
         "key_drills": "Two-bounce rally games, alternating forehand-backhand feed drills",
         "fitness": "Mirror movement – partner agility shadowing across the net"},
        {"session": 4, "focus": "Serve – legal underhand mechanics",
         "key_drills": "Serve-and-move drill: serve, then sprint to kitchen line",
         "fitness": "Serve accuracy target game: zones marked on court"},
        {"session": 5, "focus": "First full rally game – serve to point",
         "key_drills": "King of the court mini-tournament (5-point games)",
         "fitness": "Fitness circuit: shuffles, baseline sprints, footwork ladder"},
    ],
    2: [
        {"session": 6, "focus": "Non-volley zone rules – what, why, how",
         "key_drills": "Kitchen line positioning drill: approach practice from mid-court",
         "fitness": "Cone slalom sprint – first to kitchen line and back"},
        {"session": 7, "focus": "Dink mechanics – soft hands, wrist control",
         "key_drills": "Cross-court dink rally (target: 5 consecutive), partner challenge",
         "fitness": "Dink battle: first to 10 dinks wins; loser does lateral shuffles"},
        {"session": 8, "focus": "Third shot introduction – purpose and execution",
         "key_drills": "Serve → return → third shot drop sequence, repeated in pairs",
         "fitness": "Competitive serve-to-third-shot rally: points for clean drops"},
        {"session": 9, "focus": "Movement at the kitchen – split step, lateral reach",
         "key_drills": "Live kitchen engagement: dink or reset under pressure drills",
         "fitness": "Agility ladder + kitchen line dash circuit (coach calls direction)"},
        {"session": 10, "focus": "Game day with kitchen rules fully applied",
         "key_drills": "Full match play: rally scoring, full court rules, proper call-outs",
         "fitness": "🏋️ FITNESS TEST: Timed court shuttles, recorded for Week 4"},
    ],
    3: [
        {"session": 11, "focus": "Doubles positioning – stacking, poaching introduction",
         "key_drills": "2v2 position drills: designated court zones, rotating roles",
         "fitness": "Competitive doubles rallies: team with best court coverage wins"},
        {"session": 12, "focus": "Return of serve mechanics and placement",
         "key_drills": "Return + transition drill: return wide, sprint to kitchen",
         "fitness": "Sprint-to-kitchen race: fastest transition in a live rally"},
        {"session": 13, "focus": "Attacking the mid-court – when to speed up",
         "key_drills": "Speedup drill: dink-dink-drive trigger practice, pair volleys",
         "fitness": "Reaction volley circuit: coach feeds rapid volleys, player defends"},
        {"session": 14, "focus": "Reset mechanics – how to slow down a fast game",
         "key_drills": "Reset drill: player receives drives, converts to dink under pressure",
         "fitness": "Mental resilience game: points restart at 0 after every 3 consecutive errors"},
        {"session": 15, "focus": "Full competitive match day – observed by coach",
         "key_drills": "Doubles tournament: round-robin format, proper scoring, coach observation",
         "fitness": "Endurance finisher: 3-min continuous rally – group must hit 50 shots"},
    ],
    4: [
        {"session": 16, "focus": "Full skill review – player self-assessment",
         "key_drills": "Players call their own weakest skill; coach designs 15-min focused drill block",
         "fitness": "🏋️ FITNESS TEST: Court shuttles – compare to Day 10 baseline"},
        {"session": 17, "focus": "Serve and serve-return pressure session",
         "key_drills": "Serve pressure game: 10 consecutive serves, progressively smaller zones",
         "fitness": "Reaction sprint game: serve-and-sprint relay format between pairs"},
        {"session": 18, "focus": "Kitchen game mastery – dink battles and resets under fatigue",
         "key_drills": "Dink battle under fatigue: run two court lengths, then dink rally immediately",
         "fitness": "Stamina circuit: 4 rounds of shuffle, sprint, dink – 6 minutes continuous"},
        {"session": 19, "focus": "Strategy session – game planning for different opponents",
         "key_drills": "Game simulation: coach sets scenarios ('they attack your backhand – what's your plan?')",
         "fitness": "Mental game: silent points – no talking, coaching players to think independently"},
        {"session": 20, "focus": "Month-end showcase and celebration",
         "key_drills": "Final tournament: full doubles round-robin with proper scoring",
         "fitness": "Closing ceremony: coach reviews every player's growth, sets personal goal for Month 2"},
    ],
}

SKILLS = ["grip", "serve", "forehand", "backhand", "dink", "movement"]

# ─────────────────────────────────────────────
#  APP CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="RallyGully Academy",
    page_icon=_FAVICON if os.path.isfile(_FAVICON) else "🏓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS (RallyGully brand: high-contrast black text) ─────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&display=swap');
html, body, [data-testid="stAppViewContainer"] {{
    background: {RG_BG} !important;
    color: {RG_TEXT} !important;
    font-family: 'Nunito', 'Segoe UI', sans-serif !important;
}}
/* Main area: default Streamlit text → black */
[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] li,
[data-testid="stAppViewContainer"] .stMarkdown,
[data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] {{
    color: {RG_TEXT} !important;
}}
[data-testid="stAppViewContainer"] [data-testid="stWidgetLabel"] p,
[data-testid="stAppViewContainer"] label,
[data-testid="stVerticalBlock"] label {{
    color: {RG_TEXT} !important;
}}
[data-testid="stCaptionContainer"] {{
    color: {RG_MUTED} !important;
}}
[data-testid="metric-container"] label,
[data-testid="metric-container"] [data-testid="stMetricValue"],
[data-testid="metric-container"] [data-testid="stMetricLabel"],
[data-testid="metric-container"] [data-testid="stMetricDelta"] {{
    color: {RG_TEXT} !important;
}}
[data-testid="metric-container"] {{
    background: {RG_CARD};
    border: 1px solid {RG_BORDER};
    border-radius: 12px;
    padding: 1rem;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}}
/* Light sidebar: black labels + visible logo card */
[data-testid="stSidebar"] {{
    background: #f2f2f4 !important;
    border-right: 1px solid #ccc !important;
}}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {{
    color: {RG_TEXT} !important;
}}
[data-testid="stSidebar"] [data-baseweb="radio"] label {{
    color: {RG_TEXT} !important;
}}
/* Logo strip: high contrast behind favicon / wordmark */
[data-testid="stSidebar"] [data-testid="stImage"] {{
    background: #ffffff;
    border: 1px solid #ccc;
    border-radius: 12px;
    padding: 12px;
    margin-bottom: 4px;
    display: flex;
    justify-content: center;
    align-items: center;
}}
[data-testid="stSidebar"] [data-testid="stImage"] img {{
    margin: 0 auto;
}}
.rg-pill {{
    display: inline-block;
    background: {RG_ORANGE_SOFT};
    border: 1px solid {RG_ORANGE};
    color: {RG_TEXT};
    border-radius: 20px;
    padding: 2px 14px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-bottom: 6px;
}}
.rg-card {{
    background: {RG_CARD};
    border: 1px solid {RG_BORDER};
    border-radius: 14px;
    padding: 1.2rem 1.4rem;
    margin-bottom: 1rem;
    color: {RG_TEXT} !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05);
}}
.rg-card-accent {{
    border-left: 4px solid {RG_ORANGE};
}}
.curr-cell {{
    background: #fff;
    border: 1px solid {RG_BORDER};
    border-radius: 10px;
    padding: 0.8rem 1rem;
    margin-bottom: 0.6rem;
    font-size: 0.88rem;
    color: {RG_TEXT} !important;
}}
.curr-focus {{ color: {RG_TEXT} !important; font-weight: 700; font-size: 0.95rem; }}
.curr-label {{ color: {RG_MUTED} !important; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.06em; }}
.rg-warn {{
    background: {RG_ORANGE_SOFT};
    border: 1px solid {RG_ORANGE};
    border-radius: 10px;
    padding: 0.7rem 1rem;
    color: {RG_TEXT} !important;
    font-size: 0.88rem;
    margin-bottom: 0.8rem;
}}
.rg-ok {{
    background: #e8f5e9;
    border: 1px solid #43a047;
    border-radius: 10px;
    padding: 0.7rem 1rem;
    color: {RG_TEXT} !important;
    font-size: 0.88rem;
    margin-bottom: 0.8rem;
}}
h1, h2, h3 {{ color: {RG_TEXT} !important; }}
.big-title {{
    font-size: 2rem;
    font-weight: 800;
    color: {RG_TEXT} !important;
    letter-spacing: -0.03em;
}}
.sub-title {{ color: {RG_MUTED} !important; font-size: 0.95rem; margin-top: -0.4rem; }}
[data-testid="stDataFrame"] {{ border-radius: 10px; overflow: hidden; }}
[data-testid="stDataFrame"] div[data-testid="StyledDataFrameDataEditor"] {{
    color: {RG_TEXT} !important;
}}
/* Primary actions + form submit — white label on brand orange (fixes dark-on-dark) */
.stButton > button,
.stButton > button > div > p,
.stButton > button span,
button[kind="primary"],
[data-testid="stBaseButton-primary"] > button,
[data-testid="stBaseButton-primary"] button {{
    background: {RG_ORANGE} !important;
    color: #ffffff !important;
    border-radius: 10px !important;
    font-weight: 800 !important;
    border: 2px solid #c25700 !important;
}}
.stButton > button:hover,
[data-testid="stBaseButton-primary"] > button:hover,
[data-testid="stBaseButton-primary"] button:hover {{
    background: #e08510 !important;
    color: #ffffff !important;
}}
[data-testid="stFormSubmitButton"] > button,
[data-testid="stFormSubmitButton"] button,
[data-testid="stFormSubmitButton"] button p,
[data-testid="stFormSubmitButton"] button span {{
    background: {RG_ORANGE} !important;
    color: #ffffff !important;
    border-radius: 10px !important;
    font-weight: 800 !important;
    border: 2px solid #c25700 !important;
}}
[data-testid="stFormSubmitButton"] > button:hover,
[data-testid="stFormSubmitButton"] button:hover {{
    background: #e08510 !important;
    color: #ffffff !important;
}}
/* Secondary Streamlit buttons — readable grey, not near-black text */
[data-testid="stBaseButton-secondary"] > button,
[data-testid="stBaseButton-secondary"] button {{
    background: #4a4a4a !important;
    color: #ffffff !important;
    border: 1px solid #333 !important;
}}
[data-testid="stBaseButton-secondary"] > button:hover {{
    background: #333333 !important;
    color: #ffffff !important;
}}
[data-testid="stRadio"] label {{ color: {RG_TEXT} !important; }}
[data-testid="stTextInput"] input,
[data-testid="stSelectbox"] select,
textarea {{
    background: {RG_CARD} !important;
    color: {RG_TEXT} !important;
    border: 1px solid #999 !important;
    border-radius: 8px !important;
}}
[data-testid="stExpander"] {{
    background: {RG_CARD} !important;
    border: 1px solid {RG_BORDER} !important;
    border-radius: 10px !important;
    color: {RG_TEXT} !important;
}}
[data-testid="stExpander"] p, [data-testid="stExpander"] span {{
    color: {RG_TEXT} !important;
}}
[data-testid="stTabs"] button {{ color: {RG_MUTED} !important; }}
[data-testid="stTabs"] button[aria-selected="true"] {{
    color: {RG_TEXT} !important;
    border-bottom: 3px solid {RG_ORANGE} !important;
}}
[data-testid="stHeader"] {{
    background: {RG_CARD} !important;
    border-bottom: 1px solid {RG_BORDER};
}}
[data-testid="stSlider"] label {{ color: {RG_TEXT} !important; }}
[data-testid="stNumberInput"] label {{ color: {RG_TEXT} !important; }}
[data-testid="stMultiSelect"] label {{ color: {RG_TEXT} !important; }}
[data-testid="stCheckbox"] label {{ color: {RG_TEXT} !important; }}
/* Avoid cramped form columns (password / submit overlap) */
[data-testid="stForm"] [data-testid="column"] {{
    min-width: 0 !important;
}}
[data-testid="stForm"] [data-baseweb="input"] {{
    min-height: 2.75rem;
}}
[data-testid="stAlert"] p,
[data-testid="stAlert"] div,
[data-testid="stAlert"] span,
div.stAlert p, div.stAlert span {{
    color: {RG_TEXT} !important;
}}
[data-testid="stToast"] p {{ color: {RG_TEXT} !important; }}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  SIDEBAR  – PORTAL SELECTOR
# ─────────────────────────────────────────────
with st.sidebar:
    if os.path.isfile(_FAVICON):
        st.image(_FAVICON, width=160)
    else:
        st.markdown(
            '<p style="color:#000;font-weight:800;font-size:1.2rem;margin:0;">RallyGully</p>',
            unsafe_allow_html=True,
        )
    st.markdown(
        '<p style="text-align:center;color:#000;font-weight:800;font-size:1.02rem;margin:0 0 6px 0;">'
        "RallyGully Academy</p>",
        unsafe_allow_html=True,
    )
    st.markdown("---")
    portal = st.radio("**Select Portal**", ["🏃 Athlete", "🎾 Coach", "⚙️ Admin"], index=0)
    st.markdown("---")
    st.markdown(
        '<p style="color:#000;font-size:0.82rem;margin:0;">Your movement for pickleball starts here.</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p style="font-size:0.82rem;margin:0.5rem 0 0 0;"><a href="https://www.rallygully.com/" target="_blank" rel="noopener" '
        'style="color:#000;font-weight:700;text-decoration:underline;">rallygully.com</a></p>',
        unsafe_allow_html=True,
    )

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
def radar_chart(scores: dict, title="Skill Radar"):
    categories = list(scores.keys())
    values = list(scores.values())
    fig = go.Figure(go.Scatterpolar(
        r=values + [values[0]],
        theta=categories + [categories[0]],
        fill='toself',
        fillcolor='rgba(93,38,137,0.18)',
        line=dict(color=RG_PURPLE, width=2),
    ))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0,10], color=RG_MUTED,
                                   gridcolor=RG_BORDER, linecolor=RG_BORDER),
                   angularaxis=dict(color=RG_TEXT, gridcolor=RG_BORDER)),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font_color=RG_TEXT, title=dict(text=title, font=dict(color=RG_TEXT, size=14)),
        showlegend=False, margin=dict(l=50,r=50,t=50,b=30), height=320,
    )
    return fig

def line_chart(df, x, y_cols, title="Progress Over Weeks"):
    colors = [RG_PURPLE, RG_ORANGE, '#2E7D32', '#1565C0', '#C62828', '#6A1B9A']
    fig = go.Figure()
    for i, col in enumerate(y_cols):
        fig.add_trace(go.Scatter(x=df[x], y=df[col], name=col.capitalize(),
                                  mode='lines+markers',
                                  line=dict(color=colors[i % len(colors)], width=2),
                                  marker=dict(size=7)))
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font_color=RG_TEXT, title=dict(text=title, font=dict(color=RG_TEXT, size=14)),
        xaxis=dict(color=RG_MUTED, gridcolor=RG_BORDER),
        yaxis=dict(color=RG_MUTED, gridcolor=RG_BORDER, range=[0,10]),
        legend=dict(bgcolor='rgba(0,0,0,0)', font=dict(color=RG_TEXT)),
        margin=dict(l=10,r=10,t=40,b=10), height=280,
    )
    return fig

def bar_chart(labels, values, title="", color=None):
    c = color or RG_ORANGE
    fig = go.Figure(go.Bar(x=labels, y=values,
                            marker_color=[c]*len(labels),
                            marker_line_color='rgba(0,0,0,0)'))
    fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                      font_color=RG_TEXT, title=dict(text=title, font=dict(color=RG_TEXT, size=13)),
                      xaxis=dict(color=RG_MUTED, gridcolor=RG_BORDER),
                      yaxis=dict(color=RG_MUTED, gridcolor=RG_BORDER),
                      margin=dict(l=10,r=10,t=40,b=10), height=240)
    return fig

def session_checklist_label(done):
    return "✅" if done else "❌"

# ─────────────────────────────────────────────
#  PORTAL 1:  ATHLETE
# ─────────────────────────────────────────────
if portal == "🏃 Athlete":
    athletes = load("athletes")
    batches  = load("batches")
    venues   = load("venues")
    perf     = load("performance")
    feedback = load("feedback")

    # ── Auth ─────────────────────────────────
    if "athlete_id" not in st.session_state:
        st.session_state.athlete_id = None

    if st.session_state.athlete_id is None:
        h1, h2 = st.columns([1, 4])
        with h1:
            if os.path.isfile(_FAVICON):
                st.image(_FAVICON, width=88)
        with h2:
            st.markdown('<div class="big-title">Athlete Portal</div>', unsafe_allow_html=True)
            st.markdown('<div class="sub-title">RallyGully Pickleball Academy · Register, train, track growth</div>', unsafe_allow_html=True)
        st.markdown("---")

        tab_login, tab_register = st.tabs(["Login", "Register"])

        with tab_login:
            email_in = st.text_input("Email", key="al_email")
            pass_in  = st.text_input("Password", type="password", key="al_pass")
            if st.button("Login", key="al_login"):
                match = None
                for k, v in athletes.items():
                    if (v.get("email") or "").strip().lower() != (email_in or "").strip().lower():
                        continue
                    ok, new_h = rg_security.verify_or_rehash(v.get("password") or "", pass_in)
                    if ok:
                        match = k
                        if new_h:
                            athletes[k]["password"] = new_h
                            save("athletes", athletes)
                        break
                if match:
                    st.session_state.athlete_id = match
                    st.rerun()
                else:
                    st.error("Invalid credentials.")

        with tab_register:
            venues_r = load("venues")
            batches_r = load("batches")
            coaches_r = load("coaches")
            athletes_r = load("athletes")
            active_vids = [k for k, v in venues_r.items() if v.get("active", True)]
            if not active_vids:
                st.warning("Registration is paused until an admin adds at least one active venue.")
            else:
                with st.form("reg_form"):
                    st.markdown("#### Join RallyGully Academy")
                    st.caption(
                        "You choose a **venue** and a **batch time**; your coach is the one assigned to that batch at that venue."
                    )
                    st.markdown("**1. Contact & profile**")
                    rname = st.text_input("Full name *", placeholder="As on ID / school records")
                    remail = st.text_input("Email *", placeholder="you@email.com")
                    rphone = st.text_input("Phone (WhatsApp) *", placeholder="+91 …")
                    rexp = st.selectbox(
                        "Pickleball experience *",
                        ["New to pickleball", "< 6 months", "6–24 months", "2+ years / competitive"],
                    )
                    remg = st.text_input("Emergency contact *", placeholder="Name + phone number")
                    rpass = st.text_input("Password *", type="password")
                    st.markdown("**2. Venue & schedule**")
                    rv = st.selectbox(
                        "Training venue *",
                        active_vids,
                        format_func=lambda k: _venue_option_label(venues_r, k),
                        help="Venues link coaches, courts, and batch templates. Pick where you will train.",
                    )
                    ch_ids = _coaches_at_venue(rv, coaches_r)
                    ch_lbl = ", ".join(coaches_r[c]["name"] for c in ch_ids) if ch_ids else "—"
                    st.caption(f"**Coaches at this venue:** {ch_lbl}")
                    presets_v = _presets_for_venue(rv, batches_r)
                    fixed_labels = [p["label"] for p in presets_v]
                    schedule_options = fixed_labels + ["Other (custom — admin assigns a slot)"]
                    batch_choice = st.radio(
                        "Batch time preference *",
                        schedule_options,
                        help="Only slots that exist at your venue are listed. “Other” joins the waitlist for manual assignment.",
                    )
                    other_detail = ""
                    rbatch = None
                    prog = "3-Day"
                    if batch_choice.startswith("Other"):
                        other_detail = st.text_input(
                            "Describe preferred days & times *",
                            placeholder="e.g. Weekend mornings, 7–8 PM …",
                        )
                        prog_pick = st.selectbox(
                            "Preferred programme *",
                            ["3-Day (Mon/Wed/Fri or Tue/Thu/Sat)", "5-Day (Mon–Fri)"],
                        )
                        prog = "3-Day" if prog_pick.startswith("3-Day") else "5-Day"
                        rbatch = OTHER_BATCH_ID
                    else:
                        preset = next(p for p in presets_v if p["label"] == batch_choice)
                        rbatch = preset["batch_id"]
                        prog = preset["program"]
                    st.markdown("**3. Optional**")
                    rnotes = st.text_input(
                        "Medical notes, dominant hand, or goals (optional)",
                        placeholder="Anything coaches should know",
                        key="reg_notes_opt",
                    )
                    submitted = st.form_submit_button("Submit registration")
                    if submitted:
                        need = []
                        if not (rname or "").strip():
                            need.append("full name")
                        if not (remail or "").strip():
                            need.append("email")
                        if not (rphone or "").strip():
                            need.append("phone")
                        if not (remg or "").strip():
                            need.append("emergency contact")
                        if not rpass:
                            need.append("password")
                        elif len(rpass) < (10 if rg_security.is_production() else 6):
                            need.append(
                                f"password (min {10 if rg_security.is_production() else 6} characters)"
                            )
                        if batch_choice.startswith("Other") and not (other_detail or "").strip():
                            need.append("schedule description")
                        em = (remail or "").strip().lower()
                        if em and any((v.get("email") or "").lower() == em for v in athletes_r.values()):
                            st.error("This email is already registered — open the **Login** tab.")
                        elif need:
                            st.error("Please complete: " + ", ".join(need) + ".")
                        elif rbatch not in batches_r:
                            st.error("Selected batch is not available. Contact the academy.")
                        else:
                            new_id = f"A{str(len(athletes_r)+1).zfill(3)}"
                            athletes_r[new_id] = {
                                "name": (rname or "").strip(),
                                "email": em,
                                "password": rpass,
                                "phone": (rphone or "").strip(),
                                "experience": rexp,
                                "emergency_contact": (remg or "").strip(),
                                "venue_id": rv,
                                "batch": rbatch,
                                "program": prog,
                                "week": 1,
                                "join_date": str(date.today()),
                                "sessions_attended": 0,
                            }
                            if (other_detail or "").strip():
                                athletes_r[new_id]["batch_time_note"] = other_detail.strip()
                            if (rnotes or "").strip():
                                athletes_r[new_id]["notes"] = (rnotes or "").strip()
                            batches_r[rbatch].setdefault("athlete_ids", [])
                            batches_r[rbatch]["athlete_ids"].append(new_id)
                            save("athletes", athletes_r)
                            save("batches", batches_r)
                            perf[new_id] = {}
                            save("performance", perf)
                            st.success(f"Registered. Your athlete ID: **{new_id}**. Log in with your email and password.")
        st.stop()

    # ── Logged-in Athlete ─────────────────────
    aid = st.session_state.athlete_id
    athlete = athletes[aid]
    batch   = batches.get(athlete["batch"], {})
    prog    = athlete.get("program", "3-Day")
    curr    = CURRICULUM_3DAY if prog == "3-Day" else CURRICULUM_5DAY
    total_sessions = 12 if prog == "3-Day" else 20
    sessions_done  = athlete.get("sessions_attended", 0)
    pct = int(sessions_done / total_sessions * 100)

    with st.sidebar:
        st.markdown(f"**{athlete['name']}**")
        st.markdown(f'<span style="color:{RG_MUTED}">{prog} Programme</span>', unsafe_allow_html=True)
        _vid = athlete.get("venue_id") or batch.get("venue_id")
        if _vid and _vid in venues:
            st.markdown(
                f'<span style="color:{RG_MUTED};font-size:0.88rem;">Venue: **{venues[_vid]["name"]}**</span>',
                unsafe_allow_html=True,
            )
        st.markdown(f"Week **{athlete.get('week',1)}** of 4")
        if st.button("Logout", key="ath_logout"):
            st.session_state.athlete_id = None
            st.rerun()

    st.markdown(
        f'<div class="big-title">Hey, {_esc(athlete["name"].split()[0])} 👋</div>',
        unsafe_allow_html=True,
    )
    _vshow = ""
    if athlete.get("venue_id") and athlete["venue_id"] in venues:
        _vshow = f" · {venues[athlete['venue_id']]['name']}"
    st.markdown(
        f'<div class="sub-title">Week {athlete.get("week",1)} · {batch.get("name","—")} · {prog}{_vshow}</div>',
        unsafe_allow_html=True,
    )
    if athlete.get("batch_time_note"):
        st.caption(f"Your requested schedule: {athlete['batch_time_note']}")
    st.markdown("---")

    nav = st.tabs(["📊 My Dashboard", "📅 My Curriculum", "📝 Coach Feedback"])

    # ── TAB 1: Dashboard ──────────────────────
    with nav[0]:
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Sessions Done", f"{sessions_done}/{total_sessions}")
        c2.metric("Month Progress", f"{pct}%")
        c3.metric("Current Week", f"{athlete.get('week',1)} / 4")
        c4.metric("Batch", batch.get("name","—")[:15]+"…" if len(batch.get("name","")) > 15 else batch.get("name","—"))

        st.markdown("")

        athlete_perf = perf.get(aid, {})
        weeks_available = sorted(athlete_perf.keys())

        if weeks_available:
            col_left, col_right = st.columns([1,1])
            with col_left:
                latest_week = weeks_available[-1]
                latest_scores = athlete_perf[latest_week]
                st.plotly_chart(radar_chart(latest_scores, f"Skill Profile – {latest_week.upper()}"),
                                use_container_width=True)

            with col_right:
                if len(weeks_available) > 1:
                    rows = []
                    for wk in weeks_available:
                        row = {"Week": wk.upper()}
                        row.update(athlete_perf[wk])
                        rows.append(row)
                    df = pd.DataFrame(rows)
                    fig = line_chart(df, "Week", SKILLS, "Skill Progression")
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.markdown(f'<div class="rg-card"><div class="curr-label">Progress Chart</div><br><span style="color:{RG_MUTED}">Available after Week 2 data is recorded by your coach.</span></div>', unsafe_allow_html=True)

            # Weakest / strongest
            sc = latest_scores
            strongest = max(sc, key=sc.get)
            weakest   = min(sc, key=sc.get)
            st.markdown(f"""
            <div class="rg-card rg-card-accent">
            <div class="curr-label">Your Snapshot</div>
            <br>
            💪 <b>Strongest skill:</b> {strongest.capitalize()} ({sc[strongest]}/10)<br>
            🎯 <b>Focus area:</b> {weakest.capitalize()} ({sc[weakest]}/10) — bring this up this week.
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="rg-card"><span style="color:{RG_MUTED}">Performance data will appear after your coach records your first session scores.</span></div>', unsafe_allow_html=True)

        # Attendance heatmap (simple)
        st.markdown("#### Attendance")
        sessions_data = load("sessions")
        my_sessions = [s for s in sessions_data.values() if aid in s.get("attendance", [])]
        att_pct = int(len(my_sessions) / max(sessions_done, 1) * 100) if my_sessions else 0

        attended_text = " · ".join(
            [f"✅ {_esc(s.get('program_session', ''))}" for s in my_sessions[:6]]
        )
        if not attended_text: attended_text = "No sessions recorded yet."
        st.markdown(f'<div class="rg-card">{attended_text}</div>', unsafe_allow_html=True)

    # ── TAB 2: Curriculum ─────────────────────
    with nav[1]:
        st.markdown('<div class="rg-pill">Programme Curriculum</div>', unsafe_allow_html=True)
        st.markdown(f"**{prog} Beginner Foundations** — 4-Week Plan")
        st.markdown("")

        current_week = athlete.get("week", 1)
        for wk_num in range(1, 5):
            sessions_in_week = curr[wk_num]
            label = "← **You are here**" if wk_num == current_week else ("✅ Completed" if wk_num < current_week else "🔒 Upcoming")
            with st.expander(f"**Week {wk_num}** — {['Court & First Contact','The Kitchen & Soft Game','Patterns & Game Intelligence','Consolidation & Identity'][wk_num-1]}  {label}", expanded=(wk_num==current_week)):
                for s in sessions_in_week:
                    sn = s['session']
                    done_marker = "✅ " if sn <= sessions_done else "  "
                    st.markdown(f"""
                    <div class="curr-cell">
                    <div class="curr-focus">{done_marker}Session {sn}</div>
                    <div class="curr-label" style="margin-top:4px">Focus</div>
                    {s['focus']}
                    <div class="curr-label" style="margin-top:8px">Key Drills</div>
                    {s['key_drills']}
                    <div class="curr-label" style="margin-top:8px">Fitness</div>
                    {s['fitness']}
                    </div>""", unsafe_allow_html=True)

    # ── TAB 3: Coach Feedback ─────────────────
    with nav[2]:
        st.markdown('<div class="rg-pill">Weekly Coach Feedback</div>', unsafe_allow_html=True)
        st.markdown("Your feedback is **anonymous** — coaches see ratings without names.")
        st.markdown("")

        # Check if already submitted this week
        my_feedback = [f for f in feedback if f.get("athlete_id") == aid]
        current_week = athlete.get("week", 1)
        already_submitted = any(f.get("week") == current_week for f in my_feedback)

        if already_submitted:
            st.markdown('<div class="rg-ok">✅ You\'ve submitted feedback for this week. Thank you!</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="rg-warn">📣 Week {current_week} feedback is pending — take 2 mins to help your coach improve.</div>', unsafe_allow_html=True)

        with st.form("feedback_form"):
            st.markdown(f"**Week {current_week} Feedback**")
            q1 = st.slider("Session energy & intensity", 1, 10, 7)
            q2 = st.slider("Coach explanation clarity", 1, 10, 7)
            q3 = st.slider("Drill quality & variety", 1, 10, 7)
            q4 = st.slider("I felt challenged & pushed", 1, 10, 7)
            comment = st.text_area("Any comments for your coach? (anonymous)", height=90)
            sub = st.form_submit_button("Submit Feedback")
            if sub:
                coach_id = batch.get("coach_id", "")
                feedback.append({
                    "athlete_id": aid, "coach_id": coach_id,
                    "week": current_week, "date": str(date.today()),
                    "session_energy": q1, "explanation_clarity": q2,
                    "drill_quality": q3, "felt_challenged": q4,
                    "comment": comment,
                })
                save("feedback", feedback)
                st.success("Feedback submitted. 🙏")
                st.rerun()

        # Past feedback summary
        if my_feedback:
            st.markdown("#### Your Past Submissions")
            for f in reversed(my_feedback[-3:]):
                avg = round((f['session_energy']+f['explanation_clarity']+f['drill_quality']+f['felt_challenged'])/4, 1)
                st.markdown(
                    f'<div class="rg-card"><b>Week {int(f["week"])}</b> &nbsp;·&nbsp; '
                    f'Avg Rating: <span style="color:{RG_TEXT}">{avg}/10</span></div>',
                    unsafe_allow_html=True,
                )


# ─────────────────────────────────────────────
#  PORTAL 2:  COACH
# ─────────────────────────────────────────────
elif portal == "🎾 Coach":
    athletes = load("athletes")
    batches  = load("batches")
    perf     = load("performance")
    feedback = load("feedback")
    coaches  = load("coaches")
    sessions_data = load("sessions")
    venues   = load("venues")

    if "coach_id" not in st.session_state:
        st.session_state.coach_id = None

    if st.session_state.coach_id is None:
        h1, h2 = st.columns([1, 4])
        with h1:
            if os.path.isfile(_FAVICON):
                st.image(_FAVICON, width=88)
        with h2:
            st.markdown('<div class="big-title">Coach Portal</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="sub-title">RallyGully Academy · Curriculum, sessions & athlete progress</div>',
                unsafe_allow_html=True,
            )
        st.markdown("---")
        email_in = st.text_input("Coach Email")
        pass_in  = st.text_input("Password", type="password")
        if st.button("Login"):
            match = None
            for k, v in coaches.items():
                if (v.get("email") or "").strip().lower() != (email_in or "").strip().lower():
                    continue
                ok, new_h = rg_security.verify_or_rehash(v.get("password") or "", pass_in)
                if ok:
                    match = k
                    if new_h:
                        coaches[k]["password"] = new_h
                        save("coaches", coaches)
                    break
            if match:
                st.session_state.coach_id = match
                st.rerun()
            else:
                st.error("Invalid credentials.")
        st.stop()

    cid   = st.session_state.coach_id
    coach = coaches[cid]
    my_batches = {
        k: v for k, v in batches.items()
        if v.get("coach_id") == cid or k in coach.get("batches", [])
    }

    with st.sidebar:
        st.markdown(f"**{coach['name']}**")
        st.markdown(f'<span style="color:{RG_MUTED}">Coach</span>', unsafe_allow_html=True)
        if st.button("Logout", key="coach_logout"):
            st.session_state.coach_id = None
            st.rerun()

    st.markdown('<div class="big-title">Coach Dashboard</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="sub-title">{_esc(coach["name"])} · {_esc(coach.get("speciality", ""))}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("---")

    nav = st.tabs(["📋 Today's Session", "👥 Athlete Performance", "📣 My Feedback", "📅 Session Log"])

    # ── TAB 1: Today's Session (Curriculum Enforcer) ──
    with nav[0]:
        st.markdown('<div class="rg-pill">Session Planner</div>', unsafe_allow_html=True)
        st.markdown("The curriculum below is **mandatory** — document what you ran after each session.")
        st.markdown("")

        if not my_batches:
            st.info("No batches assigned.")
        else:
            sel_batch_key = st.selectbox(
                "Select Batch",
                list(my_batches.keys()),
                format_func=lambda k: (
                    f"{my_batches[k]['name']} · "
                    f"{venues.get(my_batches[k].get('venue_id'), {}).get('name', my_batches[k].get('venue', ''))}"
                ),
            )
            batch = my_batches[sel_batch_key]
            prog = batch.get("program","3-Day")
            curr = CURRICULUM_3DAY if prog == "3-Day" else CURRICULUM_5DAY

            # Determine current week based on logged sessions
            my_sessions = [s for s in sessions_data.values() if s.get("batch_id") == sel_batch_key]
            sessions_logged = len(my_sessions)
            total_s = 12 if prog=="3-Day" else 20
            sessions_per_week = 3 if prog=="3-Day" else 5
            current_week = min(4, sessions_logged // sessions_per_week + 1)
            next_session_num = sessions_logged + 1

            # Find the curriculum session
            curr_session = None
            for wk, sess_list in curr.items():
                for s in sess_list:
                    if s["session"] == next_session_num:
                        curr_session = s
                        curr_week = wk
                        break

            if next_session_num > total_s:
                st.markdown('<div class="rg-ok">🎉 Programme complete for this batch! All sessions logged.</div>', unsafe_allow_html=True)
            elif curr_session:
                st.markdown(f"#### Next Session: #{next_session_num} (Week {curr_week})")
                st.markdown(f"""
                <div class="rg-card rg-card-accent">
                <div class="curr-label">Mandatory Focus</div>
                <div class="curr-focus" style="font-size:1.1rem;margin:6px 0">{curr_session['focus']}</div>
                <div class="curr-label" style="margin-top:12px">📋 Prescribed Drills</div>
                <div style="margin-top:4px">{curr_session['key_drills']}</div>
                <div class="curr-label" style="margin-top:12px">💪 Fitness Block</div>
                <div style="margin-top:4px">{curr_session['fitness']}</div>
                </div>""", unsafe_allow_html=True)

                st.markdown("#### Log This Session (required after every session)")
                with st.form("session_log_form"):
                    attendance_ids = batch.get("athlete_ids", [])
                    athlete_names  = {k: athletes[k]["name"] for k in attendance_ids if k in athletes}
                    attended = st.multiselect("Attendance", list(athlete_names.keys()),
                                              format_func=lambda k: athlete_names[k],
                                              default=list(athlete_names.keys()))

                    drills_run = st.text_area("Drills you actually ran", value=curr_session["key_drills"], height=70)
                    fitness_done = st.text_area("Fitness block", value=curr_session["fitness"], height=50)
                    c1,c2,c3 = st.columns(3)
                    sweat = c1.checkbox("✅ Sweat achieved")
                    game_block = c2.checkbox("✅ Game block done")
                    comp_moment = c3.checkbox("✅ Competitive moment")
                    coach_notes = st.text_area("Session notes (observations, player moments)", height=80)

                    # Skill scores per athlete
                    if attended:
                        st.markdown("**Skill Scores** (1–10, rate each attending player)")
                        skill_scores_entry = {}
                        for a_id in attended:
                            st.markdown(f"*{athletes[a_id]['name']}*")
                            cols = st.columns(6)
                            skill_scores_entry[a_id] = {}
                            for i, skill in enumerate(SKILLS):
                                skill_scores_entry[a_id][skill] = cols[i].number_input(skill.capitalize(), 1, 10, 7, key=f"{a_id}_{skill}")

                    submitted = st.form_submit_button("✅ Log Session")
                    if submitted:
                        if not sweat or not game_block or not comp_moment:
                            st.markdown('<div class="rg-warn">⚠️ The Rally Gully Standard requires sweat, a game block, AND a competitive moment. Check all three before logging.</div>', unsafe_allow_html=True)
                        else:
                            new_sid = f"S{str(len(sessions_data)+1).zfill(3)}"
                            sessions_data[new_sid] = {
                                "session_id": new_sid,
                                "batch_id": sel_batch_key,
                                "coach_id": cid,
                                "date": str(date.today()),
                                "week": curr_week,
                                "session_num": next_session_num,
                                "program_session": f"Week {curr_week} – Session {next_session_num}",
                                "focus": curr_session["focus"],
                                "drills_run": drills_run,
                                "fitness_done": fitness_done,
                                "game_block_done": game_block,
                                "sweat": sweat,
                                "competitive_moment": comp_moment,
                                "coach_notes": coach_notes,
                                "attendance": attended,
                            }
                            save("sessions", sessions_data)

                            # Save skill scores
                            perf_data = load("performance")
                            wk_key = f"w{curr_week}"
                            for a_id in attended:
                                if a_id not in perf_data: perf_data[a_id] = {}
                                perf_data[a_id][wk_key] = {sk: skill_scores_entry[a_id][sk] for sk in SKILLS}
                                # update athlete week
                                athletes[a_id]["sessions_attended"] = athletes[a_id].get("sessions_attended",0) + 1
                                athletes[a_id]["week"] = curr_week
                            save("performance", perf_data)
                            save("athletes", athletes)
                            st.success(f"Session #{next_session_num} logged! ✅")
                            st.rerun()

    # ── TAB 2: Athlete Performance ────────────
    with nav[1]:
        st.markdown('<div class="rg-pill">Athlete Performance Review</div>', unsafe_allow_html=True)

        all_my_athletes = []
        for bk, bv in my_batches.items():
            for aid in bv.get("athlete_ids", []):
                if aid in athletes:
                    all_my_athletes.append(aid)

        if not all_my_athletes:
            st.info("No athletes in your batches yet.")
        else:
            perf_data = load("performance")
            sel_athlete = st.selectbox("Select Athlete", all_my_athletes,
                                        format_func=lambda k: athletes[k]["name"])
            ath = athletes[sel_athlete]
            ath_perf = perf_data.get(sel_athlete, {})

            c1,c2,c3 = st.columns(3)
            c1.metric("Sessions Attended", ath.get("sessions_attended", 0))
            c2.metric("Current Week", ath.get("week", 1))
            c3.metric("Programme", ath.get("program","3-Day"))

            if ath_perf:
                weeks = sorted(ath_perf.keys())
                latest = ath_perf[weeks[-1]]

                col1, col2 = st.columns([1,1])
                with col1:
                    st.plotly_chart(radar_chart(latest, f"Latest Skill Profile ({weeks[-1].upper()})"),
                                    use_container_width=True)
                with col2:
                    if len(weeks) > 1:
                        rows = [{"Week": w.upper(), **ath_perf[w]} for w in weeks]
                        df = pd.DataFrame(rows)
                        st.plotly_chart(line_chart(df, "Week", SKILLS, "Skill Progression"),
                                        use_container_width=True)

                # Skills table
                st.markdown("#### Skill Scores by Week")
                rows = []
                for w in weeks:
                    row = {"Week": w.upper()}
                    row.update({s.capitalize(): v for s,v in ath_perf[w].items()})
                    rows.append(row)
                df = pd.DataFrame(rows).set_index("Week")
                st.dataframe(df, use_container_width=True)

                # Coach notes
                my_sessions_for_ath = [s for s in sessions_data.values()
                                        if sel_athlete in s.get("attendance",[]) and s.get("coach_id")==cid]
                if my_sessions_for_ath:
                    st.markdown("#### Coach Notes from Sessions")
                    for s in reversed(my_sessions_for_ath[-4:]):
                        if s.get("coach_notes"):
                            st.markdown(
                                f'<div class="rg-card"><b>{_esc(s.get("program_session",""))}</b> · '
                                f'{_esc(s.get("date",""))}<br><span style="color:{RG_MUTED}">'
                                f'{_esc(s.get("coach_notes",""))}</span></div>',
                                unsafe_allow_html=True,
                            )
            else:
                st.info("No performance data recorded yet. Log a session from the Today's Session tab.")

    # ── TAB 3: Anonymous Feedback ──────────────
    with nav[2]:
        st.markdown('<div class="rg-pill">Anonymous Athlete Feedback</div>', unsafe_allow_html=True)
        st.markdown("All feedback is anonymised — you see ratings and comments, not names.")
        st.markdown("")

        my_feedback = [f for f in feedback if f.get("coach_id") == cid]
        if not my_feedback:
            st.info("No feedback received yet.")
        else:
            avg_energy  = round(sum(f["session_energy"] for f in my_feedback) / len(my_feedback), 1)
            avg_clarity = round(sum(f["explanation_clarity"] for f in my_feedback) / len(my_feedback), 1)
            avg_drill   = round(sum(f["drill_quality"] for f in my_feedback) / len(my_feedback), 1)
            avg_chall   = round(sum(f["felt_challenged"] for f in my_feedback) / len(my_feedback), 1)
            overall     = round((avg_energy+avg_clarity+avg_drill+avg_chall)/4, 1)

            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("Overall", f"{overall}/10")
            c2.metric("Energy", f"{avg_energy}/10")
            c3.metric("Clarity", f"{avg_clarity}/10")
            c4.metric("Drills", f"{avg_drill}/10")
            c5.metric("Challenge", f"{avg_chall}/10")

            # Bar chart by dimension
            fig = bar_chart(
                ["Session Energy","Explanation Clarity","Drill Quality","Felt Challenged"],
                [avg_energy, avg_clarity, avg_drill, avg_chall],
                "Average Feedback Scores"
            )
            st.plotly_chart(fig, use_container_width=True)

            # Feedback by week
            weeks_in_feedback = sorted(set(f["week"] for f in my_feedback))
            if len(weeks_in_feedback) > 1:
                weekly = []
                for w in weeks_in_feedback:
                    wf = [f for f in my_feedback if f["week"]==w]
                    weekly.append({
                        "Week": f"W{w}",
                        "Energy": round(sum(f["session_energy"] for f in wf)/len(wf),1),
                        "Clarity": round(sum(f["explanation_clarity"] for f in wf)/len(wf),1),
                        "Challenge": round(sum(f["felt_challenged"] for f in wf)/len(wf),1),
                    })
                df = pd.DataFrame(weekly)
                fig2 = line_chart(df, "Week", ["Energy","Clarity","Challenge"], "Weekly Feedback Trend")
                st.plotly_chart(fig2, use_container_width=True)

            # Anonymous comments
            comments = [f.get("comment","").strip() for f in my_feedback if f.get("comment","").strip()]
            if comments:
                st.markdown("#### What athletes said (anonymous)")
                for c in comments:
                    st.markdown(
                        f'<div class="rg-card"><span style="color:{RG_MUTED};font-size:0.85rem">💬</span> '
                        f"{_esc(c)}</div>",
                        unsafe_allow_html=True,
                    )

    # ── TAB 4: Session Log ────────────────────
    with nav[3]:
        st.markdown('<div class="rg-pill">Session Log</div>', unsafe_allow_html=True)
        my_sess = [s for s in sessions_data.values() if s.get("coach_id")==cid]
        if not my_sess:
            st.info("No sessions logged yet.")
        else:
            for s in reversed(my_sess):
                chks = f"{session_checklist_label(s.get('sweat'))} Sweat  {session_checklist_label(s.get('game_block_done'))} Game  {session_checklist_label(s.get('competitive_moment'))} Compete"
                st.markdown(f"""
                <div class="rg-card">
                <b>{_esc(s.get('program_session',''))}</b> &nbsp;·&nbsp; {_esc(s.get('date',''))}
                &nbsp;&nbsp; {chks}<br>
                <span style="color:{RG_MUTED};font-size:0.85rem">{_esc(s.get('focus',''))}</span><br>
                <span style="color:{RG_MUTED};font-size:0.82rem">{_esc(s.get('coach_notes',''))}</span>
                </div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
#  PORTAL 3:  ADMIN
# ─────────────────────────────────────────────
else:
    athletes = load("athletes")
    coaches  = load("coaches")
    batches  = load("batches")
    perf     = load("performance")
    feedback = load("feedback")
    sessions_data = load("sessions")

    if "admin_auth" not in st.session_state:
        st.session_state.admin_auth = False

    if not st.session_state.admin_auth:
        h1, h2 = st.columns([1, 4])
        with h1:
            if os.path.isfile(_FAVICON):
                st.image(_FAVICON, width=88)
        with h2:
            st.markdown('<div class="big-title">Admin Portal</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="sub-title">RallyGully Academy · Venues, coaches, batches & analytics</div>',
                unsafe_allow_html=True,
            )
        st.markdown("---")
        mat, src = _admin_auth_context()
        if mat is None:
            st.error(
                "**Production mode:** set `ADMIN_PASSWORD` in `.streamlit/secrets.toml` (Streamlit Cloud) "
                "or the **`RG_ADMIN_PASSWORD`** environment variable on your host. "
                "Optional: store a bcrypt hash under `admin_password` in `rg_data/config.json`."
            )
            st.stop()
        ap = st.text_input("Admin password", type="password")
        if st.button("Login", type="primary"):
            if rg_security.verify_admin_material(ap, mat):
                if src == "file" and not rg_security.is_password_hash(mat):
                    save("config", {"admin_password": rg_security.hash_password(ap)})
                st.session_state.admin_auth = True
                st.rerun()
            else:
                st.error("Wrong password.")
        if rg_security.is_production():
            st.caption(
                "Admin password: use **Streamlit secrets** or **`RG_ADMIN_PASSWORD`** (plaintext). "
                "`config.json` may hold a bcrypt `admin_password` hash instead of plaintext."
            )
        elif src == "default":
            st.markdown(
                f'<span style="color:{RG_MUTED};font-size:0.85rem">'
                "Dev default: set <code>ADMIN_PASSWORD</code> / <code>RG_ADMIN_PASSWORD</code> / "
                f"<code>config.json</code> for production. Current dev fallback is <code>{DEFAULT_ADMIN_PASSWORD}</code>.</span>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("Password from: secrets, environment, or hashed/plain `rg_data/config.json`.")
        st.stop()

    with st.sidebar:
        st.markdown("**Admin**")
        st.markdown(f'<span style="color:{RG_MUTED}">Academy Command</span>', unsafe_allow_html=True)
        if st.button("Logout", key="admin_logout"):
            st.session_state.admin_auth = False
            st.rerun()

    st.markdown('<div class="big-title">Academy Command Centre</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Rally Gully Pickleball Academy · Full Management View</div>', unsafe_allow_html=True)
    st.markdown("---")

    # ── KPI row ──────────────────────────────
    total_athletes = len(athletes)
    total_coaches  = len(coaches)
    total_batches  = len(batches)
    total_sessions = len(sessions_data)
    active_batches = sum(1 for b in batches.values() if b.get("status")=="Active")
    avg_attendance = round(sum(a.get("sessions_attended",0) for a in athletes.values()) / max(total_athletes,1), 1)

    c1,c2,c3,c4,c5,c6 = st.columns(6)
    c1.metric("Athletes", total_athletes)
    c2.metric("Coaches", total_coaches)
    c3.metric("Total Batches", total_batches)
    c4.metric("Active Batches", active_batches)
    c5.metric("Sessions Logged", total_sessions)
    c6.metric("Avg Sessions / Athlete", avg_attendance)

    st.markdown("")

    venues = load("venues")

    nav = st.tabs(["🗺️ Venues", "🏟️ Batches", "👥 Athletes", "🎾 Coaches", "📊 Analytics", "⚙️ Setup"])

    # ── TAB 1: Venues ─────────────────────────
    with nav[0]:
        st.markdown('<div class="rg-pill">Venues & courts</div>', unsafe_allow_html=True)
        st.caption("Venues connect **coaches → batches → athletes**. Add every location where academy batches run.")
        with st.expander("➕ Add venue"):
            with st.form("add_venue_form"):
                vn = st.text_input("Venue / court name *", placeholder="e.g. South Court – Indiranagar")
                vc = st.text_input("City / area *", placeholder="Bengaluru")
                va = st.text_input("Address (optional)", placeholder="Street, landmark…")
                if st.form_submit_button("Create venue"):
                    if not (vn or "").strip() or not (vc or "").strip():
                        st.error("Name and city are required.")
                    else:
                        n = len(venues) + 1
                        vid = f"V{str(n).zfill(3)}"
                        while vid in venues:
                            n += 1
                            vid = f"V{str(n).zfill(3)}"
                        venues[vid] = {
                            "name": (vn or "").strip(),
                            "city": (vc or "").strip(),
                            "address": (va or "").strip(),
                            "active": True,
                        }
                        save("venues", venues)
                        st.success(f"Venue **{vid}** created.")
                        st.rerun()
        for vid, v in sorted(venues.items(), key=lambda x: x[1].get("name", "")):
            act = v.get("active", True)
            st.markdown(
                f'<div class="rg-card rg-card-accent"><b>{_esc(v.get("name", "—"))}</b> '
                f'<span style="color:{RG_MUTED};">({_esc(vid)})</span><br>'
                f'<span style="color:{RG_MUTED};font-size:0.9rem;">'
                f'{_esc(v.get("city", ""))} · {_esc(v.get("address", ""))}</span><br>'
                f'<span style="color:{RG_TEXT};">{"Active" if act else "Inactive"}</span></div>',
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Deactivate" if act else "Activate", key=f"vt_{vid}"):
                    venues[vid]["active"] = not act
                    save("venues", venues)
                    st.rerun()
            with c2:
                if st.button("Delete if unused", key=f"vx_{vid}"):
                    used = any(b.get("venue_id") == vid for b in batches.values()) or any(
                        a.get("venue_id") == vid for a in athletes.values()
                    )
                    if used:
                        st.error("Venue is still linked to batches or athletes — reassign first.")
                    else:
                        del venues[vid]
                        save("venues", venues)
                        st.rerun()

    # ── TAB 2: Batches ────────────────────────
    with nav[1]:
        st.markdown('<div class="rg-pill">Active Batches</div>', unsafe_allow_html=True)

        col_b, col_new = st.columns([3,1])
        with col_new:
            with st.expander("➕ New Batch"):
                with st.form("new_batch_form"):
                    nb_name  = st.text_input("Batch Name")
                    vkeys = [k for k in venues if venues[k].get("active", True)]
                    nb_vid = st.selectbox(
                        "Venue *",
                        vkeys or list(venues.keys()),
                        format_func=lambda k: _venue_option_label(venues, k),
                        help="Athletes register by venue; this links the batch to that location.",
                    )
                    nb_coach = st.selectbox("Coach *", list(coaches.keys()),
                                             format_func=lambda k: coaches[k]["name"])
                    nb_prog  = st.selectbox("Programme", ["3-Day","5-Day"])
                    nb_start = st.date_input("Start Date")
                    nb_days  = st.text_input("Days", "Mon / Wed / Fri")
                    nb_time  = st.text_input("Time", "7:00 AM")
                    if st.form_submit_button("Create"):
                        if not vkeys:
                            st.error("Add a venue first.")
                        elif not (nb_name or "").strip():
                            st.error("Batch name is required.")
                        else:
                            vnm = venues.get(nb_vid, {}).get("name", "Venue")
                            bid = f"B{str(len(batches)+1).zfill(3)}"
                            batches[bid] = {
                                "name": (nb_name or "").strip(),
                                "coach_id": nb_coach,
                                "program": nb_prog,
                                "start_date": str(nb_start),
                                "days": nb_days,
                                "time": nb_time,
                                "venue": vnm,
                                "venue_id": nb_vid,
                                "athlete_ids": [],
                                "status": "Active",
                            }
                            coaches[nb_coach].setdefault("batches", [])
                            if bid not in coaches[nb_coach]["batches"]:
                                coaches[nb_coach]["batches"].append(bid)
                            cvs = set(coaches[nb_coach].get("venue_ids", []))
                            cvs.add(nb_vid)
                            coaches[nb_coach]["venue_ids"] = list(cvs)
                            save("batches", batches)
                            save("coaches", coaches)
                            st.success(f"Batch {bid} created!")
                            st.rerun()

        for bk, bv in batches.items():
            coach_name = coaches.get(bv.get("coach_id",""),{}).get("name","—")
            n_ath = len(bv.get("athlete_ids",[]))
            prog_sessions = [s for s in sessions_data.values() if s.get("batch_id")==bk]
            total_s = 12 if bv.get("program")=="3-Day" else 20
            pct = int(len(prog_sessions)/total_s*100) if total_s else 0

            # Compliance check: all 3 must be checked per session
            compliant = all(s.get("sweat") and s.get("game_block_done") and s.get("competitive_moment")
                             for s in prog_sessions)
            comp_badge = '🟢' if compliant else '🟡'

            st.markdown(f"""
            <div class="rg-card rg-card-accent">
            <div style="display:flex;justify-content:space-between;align-items:center">
            <div>
            <b style="font-size:1.05rem;color:{RG_TEXT}">{_esc(bv.get("name",""))}</b> &nbsp;
            <span style="background:{RG_PURPLE_SOFT};border-radius:6px;padding:2px 8px;font-size:0.78rem;color:{RG_TEXT}">{_esc(bv.get("program",""))}</span>
            </div>
            <div style="color:{RG_MUTED};font-size:0.88rem">{comp_badge} Standards Compliance</div>
            </div>
            <div style="margin-top:8px;color:{RG_MUTED};font-size:0.88rem">
            👤 Coach: <b style="color:{RG_TEXT}">{_esc(coach_name)}</b> &nbsp;|&nbsp;
            🏃 Athletes: <b style="color:{RG_TEXT}">{n_ath}</b> &nbsp;|&nbsp;
            📅 {_esc(bv.get("days",""))} · {_esc(bv.get("time",""))} · {_esc(venues.get(bv.get("venue_id"),{}).get("name") or bv.get("venue","") or "—")}
            </div>
            <div style="margin-top:10px">
            <div style="background:{RG_BORDER};border-radius:6px;height:6px;overflow:hidden">
            <div style="background:{RG_ORANGE};height:100%;width:{pct}%;border-radius:6px"></div>
            </div>
            <span style="color:{RG_MUTED};font-size:0.78rem">{len(prog_sessions)}/{total_s} sessions logged ({pct}%)</span>
            </div>
            </div>""", unsafe_allow_html=True)

    # ── TAB 3: Athletes ───────────────────────
    with nav[2]:
        st.markdown('<div class="rg-pill">All Athletes</div>', unsafe_allow_html=True)

        _ath_cols = [
            "ID", "Name", "Venue", "Batch", "Coach", "Programme", "Week",
            "Sessions", "Avg Skill Score", "Schedule note",
        ]
        rows = []
        for aid, ath in athletes.items():
            ath_perf = perf.get(aid, {})
            latest_wk = max(ath_perf.keys(), default=None)
            latest_avg = round(sum(ath_perf[latest_wk].values())/len(ath_perf[latest_wk]),1) if latest_wk else "—"
            vid = ath.get("venue_id")
            vnm = venues.get(vid, {}).get("name", "—") if vid else "—"
            rows.append({
                "ID": aid,
                "Name": ath["name"],
                "Venue": vnm,
                "Batch": batches.get(ath.get("batch",""),{}).get("name","—"),
                "Coach": coaches.get(batches.get(ath.get("batch",""),{}).get("coach_id"),{}).get("name","—"),
                "Programme": ath.get("program","—"),
                "Week": ath.get("week",1),
                "Sessions": ath.get("sessions_attended",0),
                "Avg Skill Score": latest_avg,
                "Schedule note": ath.get("batch_time_note") or "—",
            })
        df = pd.DataFrame(rows, columns=_ath_cols)
        st.dataframe(df.set_index("ID"), use_container_width=True)

        # Deep dive
        if not athletes:
            st.info("No athletes yet — register from the Athlete portal or add them in Admin.")
        else:
            sel_ath = st.selectbox("View Athlete Detail", list(athletes.keys()),
                                    format_func=lambda k: athletes[k]["name"])
            ath = athletes[sel_ath]
            ath_perf = perf.get(sel_ath,{})
            if ath_perf:
                weeks = sorted(ath_perf.keys())
                col1, col2 = st.columns(2)
                with col1:
                    st.plotly_chart(radar_chart(ath_perf[weeks[-1]],
                                                 f"{ath['name']} – Latest Skills"), use_container_width=True)
                with col2:
                    if len(weeks)>1:
                        rows2 = [{"Week":w.upper(),**ath_perf[w]} for w in weeks]
                        df2 = pd.DataFrame(rows2)
                        st.plotly_chart(line_chart(df2,"Week",SKILLS,"Skill Progression"), use_container_width=True)

    # ── TAB 4: Coaches ────────────────────────
    with nav[3]:
        st.markdown('<div class="rg-pill">Coach Management</div>', unsafe_allow_html=True)
        st.caption("Assign each coach to one or more **venues** so registration and rosters stay aligned.")

        for ck, cv in coaches.items():
            my_b = [k for k in cv.get("batches",[]) if k in batches]
            n_athletes_total = sum(len(batches[b].get("athlete_ids",[])) for b in my_b)
            coach_sessions   = [s for s in sessions_data.values() if s.get("coach_id")==ck]
            coach_feedback   = [f for f in feedback if f.get("coach_id")==ck]
            avg_fb = round(sum((f["session_energy"]+f["explanation_clarity"]+f["drill_quality"]+f["felt_challenged"])/4
                               for f in coach_feedback)/max(len(coach_feedback),1),1) if coach_feedback else "—"

            # Standards compliance rate
            compliant_count = sum(1 for s in coach_sessions
                                  if s.get("sweat") and s.get("game_block_done") and s.get("competitive_moment"))
            compliance_pct  = int(compliant_count/max(len(coach_sessions),1)*100)

            vlabels = ", ".join(venues.get(v, {}).get("name", v) for v in cv.get("venue_ids", []) if v in venues) or "—"
            comp_hex = RG_TEXT if compliance_pct >= 80 else RG_MUTED
            st.markdown(f"""
            <div class="rg-card rg-card-accent">
            <b style="font-size:1.05rem;color:{RG_TEXT}">{_esc(cv.get("name",""))}</b>
            <div style="margin-top:6px;color:{RG_MUTED};font-size:0.85rem">📍 Venues: <b style="color:{RG_TEXT}">{_esc(vlabels)}</b></div>
            <div style="margin-top:8px;color:{RG_MUTED};font-size:0.88rem">
            🏟️ Batches: <b style="color:{RG_TEXT}">{len(my_b)}</b> &nbsp;|&nbsp;
            🏃 Athletes: <b style="color:{RG_TEXT}">{n_athletes_total}</b> &nbsp;|&nbsp;
            📝 Sessions Logged: <b style="color:{RG_TEXT}">{len(coach_sessions)}</b>
            </div>
            <div style="margin-top:6px;color:{RG_MUTED};font-size:0.88rem">
            ⭐ Avg Athlete Feedback: <b style="color:{RG_TEXT}">{avg_fb}/10</b> &nbsp;|&nbsp;
            ✅ RG Standards Compliance: <b style="color:{comp_hex}">{compliance_pct}%</b>
            </div>
            </div>""", unsafe_allow_html=True)

        # Add coach
        with st.expander("➕ Add coach"):
            with st.form("add_coach"):
                cn = st.text_input("Full name *")
                ce = st.text_input("Login email *")
                cp = st.text_input("Password *", type="password")
                cs = st.text_input("Speciality / certification", "Beginner Foundations")
                vk = [k for k in venues if venues[k].get("active", True)] or list(venues.keys())
                cvenues = st.multiselect(
                    "Venues this coach works at *",
                    vk,
                    format_func=lambda k: _venue_option_label(venues, k),
                    help="Athletes see coaches filtered by the venue they pick.",
                )
                if st.form_submit_button("Add coach"):
                    if not (cn or "").strip() or not (ce or "").strip() or not cp:
                        st.error("Name, email, and password are required.")
                    elif len(cp) < (10 if rg_security.is_production() else 6):
                        st.error(
                            f"Coach password must be at least {10 if rg_security.is_production() else 6} characters."
                        )
                    elif not cvenues:
                        st.error("Select at least one venue.")
                    else:
                        new_cid = f"C{str(len(coaches)+1).zfill(3)}"
                        coaches[new_cid] = {
                            "name": (cn or "").strip(),
                            "email": (ce or "").strip().lower(),
                            "password": rg_security.hash_password(cp),
                            "batches": [],
                            "venue_ids": list(cvenues),
                            "speciality": (cs or "").strip() or "Coach",
                        }
                        save("coaches", coaches)
                        st.success(f"Coach **{new_cid}** added. Assign batches under **Batches**.")
                        st.rerun()

    # ── TAB 5: Analytics ──────────────────────
    with nav[4]:
        st.markdown('<div class="rg-pill">Academy Analytics</div>', unsafe_allow_html=True)

        # Sessions logged per batch
        batch_names = {k: v["name"] for k,v in batches.items()}
        sess_counts = {k: sum(1 for s in sessions_data.values() if s.get("batch_id")==k) for k in batches}
        if sess_counts:
            fig = bar_chart(list(batch_names.values()), list(sess_counts.values()), "Sessions Logged per Batch")
            st.plotly_chart(fig, use_container_width=True)

        # Overall skill averages
        all_latest = []
        for aid in athletes:
            ap = perf.get(aid,{})
            if ap:
                latest = ap[max(ap.keys())]
                all_latest.append(latest)
        if all_latest:
            avg_skills = {sk: round(sum(w.get(sk,0) for w in all_latest)/len(all_latest),1) for sk in SKILLS}
            st.plotly_chart(radar_chart(avg_skills, "Academy-wide Average Skills"), use_container_width=True)

        # Standards compliance timeline
        comp_rows = []
        for s in sorted(sessions_data.values(), key=lambda x: x.get("date","")):
            comp_rows.append({
                "Date": s.get("date"),
                "Sweat": int(s.get("sweat",False)),
                "Game Block": int(s.get("game_block_done",False)),
                "Competitive Moment": int(s.get("competitive_moment",False)),
            })
        if comp_rows:
            df_comp = pd.DataFrame(comp_rows)
            st.markdown("#### RG Standards – Session Compliance")
            st.dataframe(df_comp, use_container_width=True)

        # Coach feedback overview
        if feedback:
            fb_rows = []
            for ck, cv in coaches.items():
                cf = [f for f in feedback if f.get("coach_id")==ck]
                if cf:
                    fb_rows.append({
                        "Coach": cv["name"],
                        "Responses": len(cf),
                        "Energy": round(sum(f["session_energy"] for f in cf)/len(cf),1),
                        "Clarity": round(sum(f["explanation_clarity"] for f in cf)/len(cf),1),
                        "Drills": round(sum(f["drill_quality"] for f in cf)/len(cf),1),
                        "Challenge": round(sum(f["felt_challenged"] for f in cf)/len(cf),1),
                    })
            if fb_rows:
                st.markdown("#### Coach Feedback Summary")
                st.dataframe(pd.DataFrame(fb_rows).set_index("Coach"), use_container_width=True)

    # ── TAB 6: Setup / Curriculum View ────────
    with nav[5]:
        st.markdown('<div class="rg-pill">Curriculum Reference</div>', unsafe_allow_html=True)

        prog_sel = st.radio("Programme", ["3-Day","5-Day"], horizontal=True)
        curr = CURRICULUM_3DAY if prog_sel=="3-Day" else CURRICULUM_5DAY

        for wk_num, sessions_in_week in curr.items():
            week_names = {1:"Court & First Contact",2:"The Kitchen & Soft Game",
                          3:"Patterns & Game Intelligence",4:"Consolidation & Identity"}
            with st.expander(f"**Week {wk_num} — {week_names[wk_num]}**"):
                for s in sessions_in_week:
                    st.markdown(f"""
                    <div class="curr-cell">
                    <div class="curr-focus">Session {s['session']}</div>
                    <div class="curr-label" style="margin-top:4px">Focus</div>
                    {s['focus']}
                    <div class="curr-label" style="margin-top:8px">Prescribed Drills</div>
                    {s['key_drills']}
                    <div class="curr-label" style="margin-top:8px">Fitness</div>
                    {s['fitness']}
                    </div>""", unsafe_allow_html=True)