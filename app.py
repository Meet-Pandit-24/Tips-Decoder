"""
Tips Decoder — Backend (Flask + Angel One SmartAPI)
Decodes a trading tip by finding the exact stock option and strike price
that matches the given current price, change, and lot size.
"""

import os
import json
import threading
import time
from datetime import date, datetime, timedelta
import re
import tempfile
import telebot

from functools import wraps
import pyotp
import requests
import pandas as pd
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from SmartApi import SmartConnect
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

from models import db, Tip, PrevCloseCache, InstrumentCache

load_dotenv()

app = Flask(__name__)
db_url = os.getenv("DATABASE_URL", "sqlite:///tips_tracker.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.getenv("SECRET_KEY", "super-secret-tips-key")
db.init_app(app)

# Telegram Bot Setup
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if TELEGRAM_BOT_TOKEN:
    bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, threaded=False)
else:
    bot = None

# Create tables if they don't exist
with app.app_context():
    db.create_all()

    # Safely add missing columns to existing Postgres table on Render
    try:
        from sqlalchemy.sql import text
        db.session.execute(text('ALTER TABLE decoded_tips ADD COLUMN "token" VARCHAR(50);'))
        db.session.commit()
        print("Successfully added 'token' column to decoded_tips table.")
    except Exception as e:
        db.session.rollback()

    try:
        from sqlalchemy.sql import text
        db.session.execute(text('ALTER TABLE decoded_tips ADD COLUMN exit_price FLOAT;'))
        db.session.commit()
        print("Successfully added 'exit_price' column to decoded_tips table.")
    except Exception as e:
        db.session.rollback()

# ── Globals ──────────────────────────────────────────────────
_smart_api: SmartConnect | None = None
_session_data: dict | None = None
_session_lock = threading.Lock()

_decode_rate_limit = {} # { "ip": [(timestamp1), (timestamp2)] }
_rate_limit_lock = threading.Lock()

_instrument_df: pd.DataFrame | None = None
_instrument_cache_date: date | None = None
_instrument_lock = threading.Lock()

_prev_close_cache = {}
_prev_close_cache_date = None
_cache_lock = threading.Lock()

_total_api_calls = 0
_api_lock = threading.Lock()

def increment_api_call(count=1):
    global _total_api_calls
    with _api_lock:
        _total_api_calls += count

INSTRUMENT_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)

# ── Angel One Session ─────────────────────────────────────────

def get_session(force_refresh: bool = False) -> SmartConnect:
    global _smart_api, _session_data
    with _session_lock:
        if _smart_api is None or _session_data is None or force_refresh:
            api_key   = os.getenv("ANGEL_API_KEY", "")
            client_id = os.getenv("ANGEL_CLIENT_ID", "")
            password  = os.getenv("ANGEL_PASSWORD", "")
            totp_sec  = os.getenv("ANGEL_TOTP_SECRET", "")

            if not all([api_key, client_id, password, totp_sec]):
                raise ValueError("Missing Angel One credentials in .env file")

            obj = SmartConnect(api_key=api_key)
            totp = pyotp.TOTP(totp_sec).now()
            
            increment_api_call()
            sess = obj.generateSession(client_id, password, totp)

            if not sess or not sess.get("status"):
                raise ConnectionError(
                    f"Angel One login failed: {sess.get('message', 'Unknown error')}"
                )

            _smart_api = obj
            _session_data = sess
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Angel One session established for {client_id}")

    return _smart_api


# ── Instrument Master ─────────────────────────────────────────

def _download_and_filter_instruments() -> list[dict]:
    """Download the ScripMaster file from Angel One and filter to F&O options only."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Downloading instrument master from Angel One...")
    resp = requests.get(INSTRUMENT_MASTER_URL, timeout=60)
    resp.raise_for_status()
    raw = resp.json()

    # Filter to F&O options only (OPTIDX + OPTSTK on NFO + BFO)
    filtered_data = [
        item for item in raw 
        if item.get("exch_seg") in ["NFO", "BFO"] 
        and item.get("instrumenttype") in ["OPTIDX", "OPTSTK"]
    ]
    
    # Free the massive raw json from memory immediately
    del raw
    print(f"  -> Filtered to {len(filtered_data):,} F&O option instruments")
    return filtered_data


def _build_dataframe(filtered_data: list[dict]) -> pd.DataFrame:
    """Convert filtered instrument data into a cleaned DataFrame."""
    df = pd.DataFrame(filtered_data)

    # Clean up columns
    df["lotsize"] = pd.to_numeric(df["lotsize"], errors="coerce").fillna(0).astype(int)
    # Angel One stores strike as integer × 100 (e.g., 24000 → 2400000)
    df["strike"] = pd.to_numeric(df["strike"], errors="coerce").fillna(0) / 100

    # Parse expiry
    df["expiry_dt"] = pd.to_datetime(df["expiry"], format="%d%b%Y", errors="coerce")

    # Option type from symbol suffix
    df["opt_type"] = df["symbol"].str[-2:]  # CE or PE

    # Underlying name (instrument name)
    df["underlying"] = df["name"].str.strip()

    return df


def refresh_instrument_cache():
    """Download ScripMaster, filter to F&O, save to DB, and update in-memory cache.
    Called by the scheduler at 9:15 AM IST on weekdays and as a fallback on first request."""
    global _instrument_df, _instrument_cache_date
    today = date.today()
    
    try:
        filtered_data = _download_and_filter_instruments()
        
        # Save to database (replace old data)
        with app.app_context():
            # Delete all old cached rows
            InstrumentCache.query.delete()
            
            # Insert new rows in batches for efficiency
            batch = []
            for item in filtered_data:
                batch.append(InstrumentCache(
                    cache_date=today,
                    token=item.get("token", ""),
                    symbol=item.get("symbol", ""),
                    name=item.get("name", ""),
                    expiry=item.get("expiry", ""),
                    strike=str(item.get("strike", "0")),
                    lotsize=str(item.get("lotsize", "0")),
                    instrumenttype=item.get("instrumenttype", ""),
                    exch_seg=item.get("exch_seg", ""),
                    tick_size=str(item.get("tick_size", ""))
                ))
                if len(batch) >= 1000:
                    db.session.bulk_save_objects(batch)
                    batch = []
            
            if batch:
                db.session.bulk_save_objects(batch)
            
            db.session.commit()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Saved {len(filtered_data):,} instruments to database (date: {today})")
        
        # Update in-memory cache
        with _instrument_lock:
            _instrument_df = _build_dataframe(filtered_data)
            _instrument_cache_date = today
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ In-memory cache updated")
            
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Failed to refresh instrument cache: {e}")


def _load_instruments_from_db() -> pd.DataFrame | None:
    """Try to load today's instruments from the database. Returns None if not found."""
    today = date.today()
    try:
        with app.app_context():
            cached = InstrumentCache.query.filter_by(cache_date=today).first()
            if cached is None:
                return None
            
            # Load all rows for today
            rows = InstrumentCache.query.filter_by(cache_date=today).all()
            data = [{
                "token": r.token,
                "symbol": r.symbol,
                "name": r.name,
                "expiry": r.expiry,
                "strike": r.strike,
                "lotsize": r.lotsize,
                "instrumenttype": r.instrumenttype,
                "exch_seg": r.exch_seg,
                "tick_size": r.tick_size
            } for r in rows]
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚡ Loaded {len(data):,} instruments from database (cached for {today})")
            return _build_dataframe(data)
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] DB load failed: {e}")
        return None


def get_instrument_df() -> pd.DataFrame:
    global _instrument_df, _instrument_cache_date
    today = date.today()

    with _instrument_lock:
        # 1. If in-memory cache is valid for today, return immediately
        if _instrument_df is not None and _instrument_cache_date == today:
            return _instrument_df

    # 2. Try loading from PostgreSQL database (fast, ~0.5 sec)
    df_from_db = _load_instruments_from_db()
    if df_from_db is not None:
        with _instrument_lock:
            _instrument_df = df_from_db
            _instrument_cache_date = today
        return _instrument_df
    
    # 3. Fallback: Download fresh from Angel One (slow, ~15-20 sec)
    # This only happens if both in-memory AND database are empty for today
    refresh_instrument_cache()
    return _instrument_df


# ── APScheduler: Refresh instruments at 9:15 AM IST on weekdays ──

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

_scheduler = BackgroundScheduler(daemon=True)
_scheduler.add_job(
    refresh_instrument_cache,
    trigger=CronTrigger(
        hour=9, minute=15,
        day_of_week='mon-fri',
        timezone=pytz.timezone('Asia/Kolkata')
    ),
    id='refresh_instruments',
    name='Refresh Angel One ScripMaster (9:15 AM IST, Mon-Fri)',
    replace_existing=True
)
_scheduler.start()
print("[Scheduler] ✅ APScheduler started — ScripMaster refresh at 9:15 AM IST (Mon-Fri)")



def get_upcoming_expiries(df: pd.DataFrame, count: int = 3) -> list[date]:
    """Return the next `count` unique expiry dates from today."""
    today = pd.Timestamp(date.today())
    future = df[df["expiry_dt"] >= today]["expiry_dt"].dropna().unique()
    future_sorted = sorted(future)
    return future_sorted[:count]


# ── Core Decode Logic ─────────────────────────────────────────

def calculate_prev_close(current_price: float, abs_change: float | None, pct_change: float | None) -> float:
    """
    Calculate the option's previous trading-day close.
    - abs_change: e.g. -1.03 (negative = price fell)
    - pct_change: e.g. -16.04 (negative = price fell)
    Returns prev_close as float.
    """
    if abs_change is not None:
        # prev_close = current - change  (if change is -1.03, prev = 5.39 - (-1.03) = 6.42)
        return current_price - abs_change
    elif pct_change is not None:
        # current = prev * (1 + pct/100)  →  prev = current / (1 + pct/100)
        return current_price / (1 + pct_change / 100)
    raise ValueError("Provide abs_change or pct_change")


def fetch_ohlc_batch(obj: SmartConnect, tokens: list[str]) -> dict[str, dict]:
    """
    Fetch OHLC for a batch of NFO tokens.
    Returns dict: token → {ltp, close (prev day close), open, high, low, tradingSymbol}
    """
    results = {}
    # API allows up to 50 tokens per request
    for i in range(0, len(tokens), 50):
        batch = tokens[i : i + 50]
        try:
            resp = obj.getMarketData("OHLC", {"NFO": batch})
            if resp and resp.get("status") and resp.get("data", {}).get("fetched"):
                for item in resp["data"]["fetched"]:
                    tok = str(item.get("symbolToken", ""))
                    results[tok] = {
                        "ltp":           float(item.get("ltp", 0) or 0),
                        "prev_close":    float(item.get("close", 0) or 0),   # close = prev day close
                        "open":          float(item.get("open", 0) or 0),
                        "high":          float(item.get("high", 0) or 0),
                        "low":           float(item.get("low", 0) or 0),
                        "tradingSymbol": item.get("tradingSymbol", ""),
                    }
        except Exception as e:
            print(f"  [WARN] OHLC batch {i}-{i+50} error: {e}")
    return results


def decode_tip(
    current_price: float,
    abs_change: float | None,
    pct_change: float | None,
    lot_size: int,
    option_type: str,          # "CE" or "PE" or "BOTH"
    expiry_scope: str,         # "nearest" | "weekly" | "monthly" | "all"
    tolerance_pct: float = 8,  # match tolerance in % of prev_close
) -> dict:
    prev_close = calculate_prev_close(current_price, abs_change, pct_change)
    tolerance  = prev_close * (tolerance_pct / 100)

    df = get_instrument_df()

    # 1. Filter by lot size OR Index Options
    if lot_size > 0:
        filtered = df[df["lotsize"] == lot_size].copy()
        if filtered.empty:
            # Try nearby lot sizes (± 1 step) to catch rounding
            nearby = [lot_size - 1, lot_size + 1, lot_size - 25, lot_size + 25]
            filtered = df[df["lotsize"].isin(nearby)].copy()
            if filtered.empty:
                return {"error": f"No instruments with lot size {lot_size}"}
    else:
        # If lot size is 0, search ALL options (both index and stock)
        filtered = df.copy()

    # 2. Filter by option type
    if option_type in ("CE", "PE"):
        filtered = filtered[filtered["opt_type"] == option_type]

    # 3. Filter by expiry scope
    today = pd.Timestamp(date.today())
    filtered = filtered[filtered["expiry_dt"] >= today]

    if expiry_scope == "nearest":
        # Check current and next expiry
        upcoming = sorted(filtered["expiry_dt"].dropna().unique())[:2]
        if upcoming:
            filtered = filtered[filtered["expiry_dt"].isin(upcoming)]
    elif expiry_scope == "weekly":
        upcoming = sorted(filtered["expiry_dt"].dropna().unique())
        if upcoming:
            # Take expiries within next 8 days
            cutoff = today + pd.Timedelta(days=8)
            filtered = filtered[filtered["expiry_dt"] <= cutoff]
    elif expiry_scope == "monthly":
        upcoming = sorted(filtered["expiry_dt"].dropna().unique())[:3]
        filtered = filtered[filtered["expiry_dt"].isin(upcoming)]
    else:
        # Limit "all" or any other scope to max 4 upcoming expiries to prevent 100-sec timeouts
        upcoming = sorted(filtered["expiry_dt"].dropna().unique())[:4]
        filtered = filtered[filtered["expiry_dt"].isin(upcoming)]

    if filtered.empty:
        return {"error": "No instruments match lot size + option type + expiry filters"}

    # 4. Filter tokens using cache to reduce API calls
    global _prev_close_cache, _prev_close_cache_date
    today_date = date.today()
    with _cache_lock:
        if _prev_close_cache_date != today_date:
            _prev_close_cache = {}
            _prev_close_cache_date = today_date
            # Pre-load cache from DB to survive Render restarts
            try:
                cached_rows = PrevCloseCache.query.filter_by(date=today_date).all()
                for r in cached_rows:
                    _prev_close_cache[r.token] = r.prev_close
                print(f"[CACHE] Loaded {len(cached_rows)} prev_close prices from DB for {today_date}")
            except Exception as e:
                print(f"[WARN] Failed to load PrevCloseCache from DB: {e}")

    tokens_by_exch = {"NFO": [], "BFO": []}
    for _, row in filtered.iterrows():
        exch = row["exch_seg"]
        tok = str(row["token"])
        
        # If in cache, check if it's within tolerance. If not, SKIP IT ENTIRELY!
        if tok in _prev_close_cache:
            diff = abs(_prev_close_cache[tok] - prev_close)
            if diff > tolerance:
                continue # Saved an API call for this token!
                
        # If not in cache, or if in cache and MATCHES tolerance, we must fetch it (to get LTP or cache it)
        if exch in tokens_by_exch:
            tokens_by_exch[exch].append(tok)
            
    # Fetch OHLC for remaining tokens
    # Fetch OHLC for remaining tokens concurrently
    obj = get_session()
    ohlc_map = {}
    api_calls_this_search = 0
    
    batches_to_fetch = []
    for exch, tkns in tokens_by_exch.items():
        for i in range(0, len(tkns), 50):
            batches_to_fetch.append((exch, tkns[i : i + 50]))
            
    if batches_to_fetch:
        print(f"Fetching {len(batches_to_fetch)} batches from Angel One...")
        
        def fetch_batch(exch, batch):
            try:
                # We do a tiny sleep based on a lock to maintain rate limits across threads
                with _instrument_lock:
                    time.sleep(0.35)
                increment_api_call()
                resp = obj.getMarketData("OHLC", {exch: batch})
                return resp
            except Exception as e:
                print(f"[WARN] OHLC batch error: {e}")
                return None

        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_batch = {executor.submit(fetch_batch, exch, batch): batch for exch, batch in batches_to_fetch}
            for future in as_completed(future_to_batch):
                api_calls_this_search += 1
                resp = future.result()
                if resp and resp.get("status") and resp.get("data", {}).get("fetched"):
                    new_caches = []
                    for item in resp["data"]["fetched"]:
                        tok = str(item.get("symbolToken", ""))
                        opt_close = float(item.get("close", 0) or 0)
                        ohlc_map[tok] = {
                            "ltp":           float(item.get("ltp", 0) or 0),
                            "prev_close":    opt_close,
                            "open":          float(item.get("open", 0) or 0),
                            "high":          float(item.get("high", 0) or 0),
                            "low":           float(item.get("low", 0) or 0),
                            "tradingSymbol": item.get("tradingSymbol", ""),
                        }
                        with _cache_lock:
                            if tok not in _prev_close_cache:
                                _prev_close_cache[tok] = opt_close
                                new_caches.append(PrevCloseCache(token=tok, date=today_date, prev_close=opt_close))
                    
                    if new_caches:
                        try:
                            # DB writes are fast, we can do them per batch
                            db.session.bulk_save_objects(new_caches)
                            db.session.commit()
                        except Exception as e:
                            db.session.rollback()

    # 5. Find matches
    matches = []
    seen_symbols = set()

    for _, row in filtered.iterrows():
        tok = str(row["token"])
        
        # If token was skipped due to cache, we skip processing it here too.
        if tok not in ohlc_map:
            # If it's in cache and matched, but API failed, we'd skip.
            # If it's in cache and didn't match, we definitely skip.
            continue
            
        mkt = ohlc_map[tok]
        opt_prev_close = mkt["prev_close"]

        if opt_prev_close <= 0:
            continue  # illiquid / no data

        diff = abs(opt_prev_close - prev_close)
        match_pct = (diff / prev_close) * 100

        if diff <= tolerance:
            key = f"{row['underlying']}_{row['strike']}_{row['opt_type']}_{row['expiry']}"
            if key in seen_symbols:
                continue
            seen_symbols.add(key)

            matches.append({
                "underlying":          row["underlying"],
                "symbol":              row["symbol"],
                "token":               tok,
                "strike":              float(row["strike"]),
                "expiry":              row["expiry"],
                "expiry_dt":           str(row["expiry_dt"].date()),
                "opt_type":            row["opt_type"],
                "lot_size":            int(row["lotsize"]),
                "ltp":                 round(mkt["ltp"], 2),
                "opt_prev_close":      round(opt_prev_close, 2),
                "calc_prev_close":     round(prev_close, 2),
                "diff":                round(diff, 2),
                "match_pct":           round(match_pct, 2),
                "match_quality":       _match_quality(match_pct),
                "open":                round(mkt["open"], 2),
                "high":                round(mkt["high"], 2),
                "low":                 round(mkt["low"], 2),
                "instrumenttype":      row["instrumenttype"],
            })

    # Sort: best match first
    matches.sort(key=lambda x: x["match_pct"])

    return {
        "calc_prev_close":  round(prev_close, 2),
        "current_price":    current_price,
        "abs_change":       abs_change,
        "pct_change":       pct_change,
        "lot_size":         lot_size,
        "option_type":      option_type,
        "expiry_scope":     expiry_scope,
        "tolerance_pct":    tolerance_pct,
        "tokens_searched":  len(ohlc_map),
        "total_matches":    len(matches),
        "api_calls_made":   api_calls_this_search,
        "matches":          matches[:25],
    }


def _match_quality(match_pct: float) -> str:
    if match_pct <= 2:
        return "EXACT"
    elif match_pct <= 5:
        return "STRONG"
    elif match_pct <= 8:
        return "GOOD"
    return "WEAK"


# ── Authentication ────────────────────────────────────────────


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # If APP_PASSWORD is not set in env, disable auth completely
        app_password = os.getenv("APP_PASSWORD")
        if not app_password:
            return f(*args, **kwargs)
            
        if not session.get('logged_in'):
            # Return 401 for API routes
            if request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized"}), 401
            # Redirect to login for pages
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/login", methods=["GET", "POST"])
def login():
    app_password = os.getenv("APP_PASSWORD")
    admin_password = os.getenv("ADMIN_PASSWORD", "superadmin")
    
    # If no password configured, just redirect to home
    if not app_password:
        session['logged_in'] = True
        session['role'] = 'admin'
        return redirect(url_for('index'))
        
    error = None
    if request.method == "POST":
        pwd = request.form.get("password")
        if pwd == admin_password:
            session['logged_in'] = True
            session['role'] = 'admin'
            return redirect(request.args.get("next") or url_for("index"))
        elif pwd == app_password:
            session['logged_in'] = True
            session['role'] = 'guest'
            return redirect(request.args.get("next") or url_for("index"))
        else:
            error = "Invalid password."
            
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.pop('logged_in', None)
    session.pop('role', None)
    return redirect(url_for("login"))


# ── Flask Routes ──────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return render_template("index.html", role=session.get("role", "admin"))


@app.route("/api/status")
@login_required
def api_status():
    try:
        obj = get_session()
        increment_api_call()
        profile = obj.getProfile(obj.refresh_token if hasattr(obj, "refresh_token") else "")
        name = profile.get("data", {}).get("name", os.getenv("ANGEL_CLIENT_ID", "Connected"))
        return jsonify({"status": "connected", "client": name})
    except Exception as e:
        # Try fresh login
        try:
            obj = get_session(force_refresh=True)
            return jsonify({"status": "connected", "client": os.getenv("ANGEL_CLIENT_ID")})
        except Exception as e2:
            return jsonify({"status": "error", "message": str(e2)}), 503


@app.route("/api/instruments/reload", methods=["POST"])
@login_required
def reload_instruments():
    global _instrument_df, _instrument_cache_date
    with _instrument_lock:
        _instrument_df = None
        _instrument_cache_date = None
    try:
        df = get_instrument_df()
        return jsonify({"status": "ok", "count": len(df)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/lot-sizes")
@login_required
def lot_sizes():
    """Return available lot sizes in NFO for autocomplete."""
    try:
        df = get_instrument_df()
        sizes = sorted(df["lotsize"].unique().tolist())
        return jsonify({"lot_sizes": sizes})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/decode", methods=["POST"])
@login_required
def decode():
    """
    POST payload:
    {
       "current_price": 10.3,
       "change": -5.55,          # either abs change or ...
       "pct_change": -35.0,      # ... pct change. Use one or the other.
       "lot_size": 1525,
       "option_type": "CE",      # "CE", "PE", or "BOTH"
       "expiry_scope": "nearest",# "nearest", "weekly", or "all"
       "tolerance_pct": 1.0
    }
    """
    
    # Simple Rate Limiter logic: 5 req per min
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    now = datetime.now()
    with _rate_limit_lock:
        if ip not in _decode_rate_limit:
            _decode_rate_limit[ip] = []
        # Filter timestamps within the last 60 seconds
        _decode_rate_limit[ip] = [t for t in _decode_rate_limit[ip] if (now - t).total_seconds() < 60]
        if len(_decode_rate_limit[ip]) >= 5:
            return jsonify({"error": "Rate limit exceeded. Please wait a minute."}), 429
        _decode_rate_limit[ip].append(now)

    body = request.get_json(force=True)
    try:
        # Validate required fields
        current_price = float(body.get("current_price", 0))
        lot_size      = int(body.get("lot_size", 0))

        # lot_size is optional now. If 0, we search all options.
        if current_price <= 0:
            return jsonify({"error": "current_price must be > 0"}), 400

        # Change: prefer abs_change, fallback to pct_change
        abs_change = body.get("abs_change")
        pct_change = body.get("pct_change")

        if abs_change is not None:
            abs_change = float(abs_change)
        if pct_change is not None:
            pct_change = float(pct_change)

        if abs_change is None and pct_change is None:
            return jsonify({"error": "Provide abs_change or pct_change"}), 400

        option_type   = body.get("option_type", "BOTH").upper()
        expiry_scope  = body.get("expiry_scope", "nearest")
        tolerance_pct = float(body.get("tolerance_pct", 8))

        result = decode_tip(
            current_price=current_price,
            abs_change=abs_change,
            pct_change=pct_change,
            lot_size=lot_size,
            option_type=option_type,
            expiry_scope=expiry_scope,
            tolerance_pct=tolerance_pct,
        )

        if "error" in result:
            return jsonify(result), 404

        return jsonify(result)

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except ConnectionError as e:
        return jsonify({"error": f"Angel One connection failed: {e}"}), 503
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/auto-trade", methods=["POST"])
def auto_trade():
    """
    Automated Webhook for Tasker / Shortcuts.
    Accepts raw text or an Image file, parses it via OCR Space, finds the match, and executes the trade.
    """
    import re
    import tempfile
    
    admin_password = os.getenv("ADMIN_PASSWORD", "superadmin")
    
    # Support both JSON payload and multipart/form-data
    if request.is_json:
        body = request.get_json(force=True)
        req_pwd = body.get("admin_password")
        raw_text = body.get("text", "")
    else:
        req_pwd = request.form.get("admin_password")
        raw_text = request.form.get("text", "")
    
    # 1. Authenticate Request
    if req_pwd != admin_password:
        return jsonify({"error": "Unauthorized"}), 403
        
    # 2. Image OCR Processing
    if 'image' in request.files:
        image_file = request.files['image']
        if image_file.filename != '':
            # We got an image! Send to OCR Space
            ocr_api_key = os.getenv("OCR_SPACE_API_KEY", "helloworld")
            
            try:
                # Save to temp file
                fd, temp_path = tempfile.mkstemp(suffix=".jpg")
                os.close(fd)
                image_file.save(temp_path)
                
                print(f"[{datetime.now().strftime('%H:%M:%S')}] OCR: Sending image to OCR Space...")
                with open(temp_path, 'rb') as f:
                    response = requests.post(
                        'https://api.ocr.space/parse/image',
                        files={'file': f},
                        data={'apikey': ocr_api_key, 'isOverlayRequired': False}
                    )
                
                os.remove(temp_path)
                
                ocr_result = response.json()
                if ocr_result.get("IsErroredOnProcessing"):
                    return jsonify({"error": "OCR API Error", "details": ocr_result.get("ErrorMessage")}), 500
                    
                parsed_text = ocr_result.get("ParsedResults", [{}])[0].get("ParsedText", "")
                raw_text += " " + parsed_text
                print(f"[{datetime.now().strftime('%H:%M:%S')}] OCR Result:\n{parsed_text}")
                
            except Exception as e:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                return jsonify({"error": f"OCR Processing failed: {str(e)}"}), 500

    if not raw_text.strip():
        return jsonify({"error": "No text or image provided, or OCR failed to read text"}), 400
        
    # 3. Parse Text
    # Try to find a decimal number (Price) and another decimal number with a sign (Change)
    # Example format: "5.39 -1.03" or "Price: 15.5 Change: +2.0"
    matches = re.search(r'(\d+\.\d+|\d+)\s+([+-]\d+\.\d+|[+-]\d+)', raw_text)
    if not matches:
        return jsonify({"error": f"Could not parse Price and Change from text: {raw_text}"}), 400
        
    try:
        current_price = float(matches.group(1))
        change = float(matches.group(2))
    except ValueError:
        return jsonify({"error": "Failed to parse matched numbers"}), 400
        
    # Optionally look for lot size or quantity
    lot_size = 0
    qty_match = re.search(r'(?:qty|lot|size|quantity)\D*(\d+)', raw_text, re.IGNORECASE)
    if qty_match:
        lot_size = int(qty_match.group(1))
        
    # Optionally look for CE / PE
    option_type = "BOTH"
    if re.search(r'\bCE\b|\bCALL\b', raw_text, re.IGNORECASE):
        option_type = "CE"
    elif re.search(r'\bPE\b|\bPUT\b', raw_text, re.IGNORECASE):
        option_type = "PE"

    # 3. Decode Tip
    try:
        decoded = decode_tip(
            current_price=current_price,
            abs_change=change,
            pct_change=None,
            lot_size=lot_size,
            option_type=option_type,
            expiry_scope="nearest",
            tolerance_pct=1.0
        )
    except Exception as e:
        return jsonify({"error": f"Decode error: {str(e)}"}), 500

    if "error" in decoded:
        return jsonify(decoded), 400
        
    matches_list = decoded.get("matches", [])
    if not matches_list:
        return jsonify({"error": "No matching options found"}), 404
        
    # 4. Check Match Quality
    best_match = matches_list[0]
    if best_match["match_quality"] not in ("EXACT", "STRONG"):
        return jsonify({
            "error": "Match quality too low to auto-trade safely", 
            "best_match": best_match["symbol"],
            "quality": best_match["match_quality"]
        }), 400
        
    # 5. Place Order
    try:
        obj = get_session()
        qty = 1 * best_match["lot_size"] # Execute 1 lot by default
        
        orderparams = {
            "variety": "NORMAL",
            "tradingsymbol": best_match["symbol"],
            "symboltoken": best_match["token"],
            "transactiontype": "BUY",
            "exchange": best_match.get("exch_seg", "NFO"),
            "ordertype": "MARKET",
            "producttype": "CARRYFORWARD",
            "duration": "DAY",
            "quantity": str(qty)
        }
        
        orderId = obj.placeOrder(orderparams)
        
        # Optionally save to DB
        tip = Tip(
            symbol=best_match["symbol"],
            token=best_match["token"],
            underlying=best_match["underlying"],
            strike=best_match["strike"],
            expiry=best_match["expiry"],
            opt_type=best_match["opt_type"],
            lot_size=best_match["lot_size"],
            instrument_type=best_match["instrumenttype"],
            entry_price=current_price,
            entry_ltp=best_match["ltp"],
            mode="TRADED",
            status="OPEN"
        )
        db.session.add(tip)
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "message": f"Auto-Trade executed: BUY {best_match['symbol']} at MARKET",
            "order_id": orderId
        })
        
    except Exception as e:
        return jsonify({"error": f"Order execution failed: {str(e)}"}), 500


@app.route("/api/order", methods=["POST"])
@login_required
def place_order():
    if session.get("role") != "admin":
        return jsonify({"error": "Forbidden. Only Admin can place real trades."}), 403
        
    try:
        body = request.get_json(force=True)
        obj = get_session()
        
        # Calculate actual quantity (Lots * Lot Size)
        lots = int(body.get("lots", 1))
        lot_size = int(body.get("lot_size", 1))
        qty = lots * lot_size

        orderparams = {
            "variety": "NORMAL",
            "tradingsymbol": body.get("symbol"),
            "symboltoken": body.get("token"),
            "transactiontype": body.get("transaction_type", "BUY"),
            "exchange": opt_info.iloc[0]["exch_seg"] if not opt_info.empty else body.get("exchange", "NFO"),
            "ordertype": body.get("order_type", "MARKET"),
            "producttype": body.get("product_type", "CARRYFORWARD"),
            "duration": "DAY",
            "quantity": str(qty)
        }
        
        if orderparams["ordertype"] == "LIMIT":
            orderparams["price"] = str(body.get("price", 0))

        increment_api_call()
        print(f"Placing Order: {orderparams}")
        
        # Bypass SDK swallowing exceptions by making a direct requests.post
        try:
            import requests
            headers = {
                "Authorization": f"Bearer {getattr(obj, 'access_token', '')}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-UserType": "USER",
                "X-SourceID": "WEB",
                "X-ClientLocalIP": getattr(obj, "clientLocalIP", "127.0.0.1"),
                "X-ClientPublicIP": getattr(obj, "clientPublicIP", "127.0.0.1"),
                "X-MACAddress": getattr(obj, "clientMacAddress", "00-00-00-00-00-00"),
                "X-PrivateKey": os.getenv("ANGEL_API_KEY")
            }
            url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/order/v1/placeOrder"
            resp = requests.post(url, json=orderparams, headers=headers)
            order_response = resp.json()
        except Exception as e:
            return jsonify({"error": f"Direct request failed: {str(e)}"}), 400
            
        print(f"Order Response: {order_response}")
        
        if not order_response:
            return jsonify({"error": "Failed to place order. Broker returned empty response."}), 400
            
        if isinstance(order_response, dict) and not order_response.get("status"):
            # Angel One returned an error dictionary
            error_msg = order_response.get("message", "Unknown broker error")
            return jsonify({"error": f"Broker Error: {error_msg}"}), 400
            
        # Success usually returns string ID directly, or a dict with status=True
        order_id = order_response.get("data", {}).get("orderid") if isinstance(order_response, dict) else order_response
        
        if not order_id:
            return jsonify({"error": "Failed to place order. No Order ID returned."}), 400
            
        return jsonify({"status": "success", "order_id": order_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Tracking Endpoints ────────────────────────────────────────

@app.route("/api/tips", methods=["POST"])
@login_required
def save_tip():
    try:
        body = request.get_json(force=True)
        tip = Tip(
            symbol=body['symbol'],
            token=body.get('token'),
            underlying=body['underlying'],
            strike=float(body['strike']),
            expiry=body['expiry'],
            opt_type=body['opt_type'],
            lot_size=int(body['lot_size']),
            instrument_type=body['instrument_type'],
            entry_price=float(body['entry_price']),
            entry_ltp=float(body['entry_ltp']),
            target_price=float(body['target_price']) if body.get('target_price') else None,
            stop_loss=float(body['stop_loss']) if body.get('stop_loss') else None,
            mode=body.get('mode', 'OBSERVER'),
            notes=body.get('notes', '')
        )
        db.session.add(tip)
        db.session.commit()
        return jsonify({"status": "success", "id": tip.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

@app.route("/api/tips", methods=["GET"])
@login_required
def get_tips():
    try:
        tips = Tip.query.order_by(Tip.timestamp.desc()).all()
        return jsonify({"tips": [t.to_dict() for t in tips]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/tips/<int:tip_id>", methods=["PUT"])
@login_required
def update_tip(tip_id):
    try:
        tip = Tip.query.get_or_404(tip_id)
        body = request.get_json(force=True)
        if 'status' in body:
            tip.status = body['status']
        if 'notes' in body:
            tip.notes = body['notes']
        if 'target_price' in body:
            tip.target_price = float(body['target_price']) if body['target_price'] else None
        if 'stop_loss' in body:
            tip.stop_loss = float(body['stop_loss']) if body['stop_loss'] else None
        if 'exit_price' in body:
            tip.exit_price = float(body['exit_price']) if body['exit_price'] else None
            
        db.session.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

@app.route("/api/tips/<int:tip_id>", methods=["DELETE"])
@login_required
def delete_tip(tip_id):
    try:
        tip = Tip.query.get_or_404(tip_id)
        db.session.delete(tip)
        db.session.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

@app.route("/api/tips/live", methods=["GET"])
@login_required
def get_tips_live():
    # Fetch live price for OPEN tips
    try:
        open_tips = Tip.query.filter_by(status='OPEN').all()
        if not open_tips:
            return jsonify({"prices": {}})
        
        # We need to map symbol to token
        # Get df to find tokens
        df = get_instrument_df()
        
        tokens_by_exch = {"NFO": [], "BFO": []}
        tip_id_to_token = {}
        
        for tip in open_tips:
            # Find the token for this tip's symbol
            match = df[df['symbol'] == tip.symbol]
            if not match.empty:
                tok = str(match.iloc[0]['token'])
                exch = str(match.iloc[0]['exch_seg'])
                tip_id_to_token[tip.id] = tok
                if exch in tokens_by_exch:
                    tokens_by_exch[exch].append(tok)
        
        obj = get_session()
        live_prices = {}
        
        for exch, tkns in tokens_by_exch.items():
            if tkns:
                for i in range(0, len(tkns), 50):
                    batch = tkns[i : i + 50]
                    try:
                        increment_api_call()
                        resp = obj.getMarketData("OHLC", {exch: batch})
                        if resp and resp.get("status") and resp.get("data", {}).get("fetched"):
                            for item in resp["data"]["fetched"]:
                                live_prices[str(item.get("symbolToken"))] = float(item.get("ltp", 0) or 0)
                    except Exception as e:
                        print(f"[WARN] Live OHLC fetch error: {e}")
                        
        # Map back to tip ID
        tip_prices = {}
        for tip_id, tok in tip_id_to_token.items():
            if tok in live_prices:
                tip_prices[tip_id] = live_prices[tok]
                
        return jsonify({"prices": tip_prices})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats", methods=["GET"])
@login_required
def get_stats():
    return jsonify({"total_api_calls": _total_api_calls})


@app.route("/api/analytics", methods=["GET"])
@login_required
def get_analytics():
    try:
        closed_tips = Tip.query.filter(Tip.status != 'OPEN').order_by(Tip.timestamp.asc()).all()
        
        realized_pl = 0
        paper_pl = 0
        real_wins = 0
        real_losses = 0
        paper_wins = 0
        paper_losses = 0
        
        daily_pl = {}
        
        for tip in closed_tips:
            date_str = tip.timestamp.strftime('%Y-%m-%d')
            if date_str not in daily_pl:
                daily_pl[date_str] = {"real": 0, "paper": 0}
                
            if tip.exit_price is not None:
                profit_per_lot = (tip.exit_price - tip.entry_price) * tip.lot_size
            elif tip.status == 'TARGET_HIT' and tip.target_price:
                profit_per_lot = (tip.target_price - tip.entry_price) * tip.lot_size
            elif tip.status == 'SL_HIT' and tip.stop_loss:
                profit_per_lot = (tip.stop_loss - tip.entry_price) * tip.lot_size
            else:
                profit_per_lot = 0
                
            if tip.mode == 'TRADED':
                realized_pl += profit_per_lot
                daily_pl[date_str]["real"] += profit_per_lot
                if profit_per_lot > 0: real_wins += 1
                elif profit_per_lot < 0: real_losses += 1
            else:
                paper_pl += profit_per_lot
                daily_pl[date_str]["paper"] += profit_per_lot
                if profit_per_lot > 0: paper_wins += 1
                elif profit_per_lot < 0: paper_losses += 1
                
        return jsonify({
            "realized_pl": realized_pl,
            "paper_pl": paper_pl,
            "real_wins": real_wins,
            "real_losses": real_losses,
            "paper_wins": paper_wins,
            "paper_losses": paper_losses,
            "daily_pl": daily_pl
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/debug-ip", methods=["GET"])
def get_debug_ip():
    """Returns the Public IP of the Render server so the user can whitelist it in Angel One."""
    import urllib.request
    try:
        ip = urllib.request.urlopen('https://api.ipify.org').read().decode('utf8')
        return jsonify({"render_public_ip": ip})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/access-logs", methods=["GET"])
@login_required
def get_access_logs():
    if session.get("role") != "admin":
        return jsonify({"error": "Forbidden"}), 403
    logs = AccessLog.query.order_by(AccessLog.timestamp.desc()).limit(100).all()
    return jsonify([{
        "id": l.id,
        "timestamp": l.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "ip_address": l.ip_address,
        "role": l.role,
        "endpoint": l.endpoint,
        "user_agent": l.user_agent
    } for l in logs])

@app.before_request
def log_request_info():
    if request.path.startswith('/static/') or request.path == '/favicon.ico':
        return
        
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    # Get role, default to unauthenticated if not logged in
    role = session.get('role', 'unauthenticated')
    
    # Fire and forget DB insertion
    try:
        log = AccessLog(
            ip_address=ip or 'unknown',
            role=role,
            endpoint=request.path,
            user_agent=request.user_agent.string[:500] if request.user_agent else ''
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        db.session.rollback()

# ── Entry Point ─────────────────────────────────────────────────────────────

def warmup():
    """Pre-load instrument master and establish Angel One session on startup."""
    try:
        get_session()
        get_instrument_df()
        print("[OK] Warmup complete - Tips Decoder is ready!")
    except Exception as e:
        print(f"[WARN] Warmup warning: {e}")
        print("   Fill in credentials in the .env file and restart.")

# Start warmup in a background thread so it doesn't block Gunicorn from starting
threading.Thread(target=warmup, daemon=True).start()

if __name__ == "__main__":
    port  = int(os.getenv("PORT", 5000))
    debug = os.getenv("DEBUG", "false").lower() == "true"

    print("=" * 55)
    print("  TIPS DECODER — Angel One SmartAPI")
    print("=" * 55)

    app.run(host="0.0.0.0", port=port, debug=debug)
# --- TELEGRAM BOT WEBHOOKS & HANDLERS ---

@app.route("/api/telegram-setup", methods=["GET"])
def telegram_setup():
    if not bot:
        return jsonify({"error": "TELEGRAM_BOT_TOKEN not set"}), 400
    host_url = request.url_root.replace("http://", "https://") 
    webhook_url = f"{host_url}api/telegram-webhook"
    bot.remove_webhook()
    success = bot.set_webhook(url=webhook_url)
    return jsonify({"status": "Webhook set", "success": success, "url": webhook_url})

@app.route("/api/telegram-webhook", methods=["POST"])
def telegram_webhook():
    if bot:
        update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
        bot.process_new_updates([update])
    return "!", 200

def _process_telegram_text(raw_text, chat_id, message_id, status_msg_id=None):
    def send_or_edit(text, markup=None):
        if status_msg_id:
            bot.edit_message_text(text, chat_id=chat_id, message_id=status_msg_id, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, text, reply_to_message_id=message_id, reply_markup=markup, parse_mode="Markdown")

    import re
    matches = re.search(r'(\d+\.\d+|\d+)\s+([+-]\d+\.\d+|[+-]\d+)', raw_text)
    if not matches:
        send_or_edit(f"❌ Could not parse Price and Change from text.")
        return
        
    try:
        current_price = float(matches.group(1))
        change = float(matches.group(2))
    except ValueError:
        send_or_edit("❌ Failed to parse matched numbers")
        return
        
    lot_size = 0
    qty_match = re.search(r'(?:qty|lot|size|quantity)\D*(\d+)', raw_text, re.IGNORECASE)
    if qty_match:
        lot_size = int(qty_match.group(1))
        
    option_type = "BOTH"
    if re.search(r'\bCE\b|\bCALL\b', raw_text, re.IGNORECASE):
        option_type = "CE"
    elif re.search(r'\bPE\b|\bPUT\b', raw_text, re.IGNORECASE):
        option_type = "PE"

    try:
        decoded = decode_tip(
            current_price=current_price,
            abs_change=change,
            pct_change=None,
            lot_size=lot_size,
            option_type=option_type,
            expiry_scope="nearest",
            tolerance_pct=1.0
        )
    except Exception as e:
        send_or_edit(f"❌ Decode error: {str(e)}")
        return

    if "error" in decoded:
        send_or_edit(f"❌ {decoded['error']}")
        return
        
    matches_list = decoded.get("matches", [])
    if not matches_list:
        send_or_edit("❌ No matching options found.")
        return
        
    best_match = matches_list[0]
    
    text = (
        f"✅ **Tip Decoded Successfully**\n\n"
        f"**Symbol:** {best_match['symbol']}\n"
        f"**Entry Price:** ₹{current_price}\n"
        f"**Lot Size:** {best_match['lot_size']}\n"
        f"**Match Quality:** {best_match['match_quality']}\n\n"
        f"📝 **Raw OCR Log:**\n"
        f"{raw_text.strip()}"
    )
    
    markup = telebot.types.InlineKeyboardMarkup()
    cb_data = f"trade_{best_match['symbol']}_{best_match['token']}_{best_match['lot_size']}"
    if len(cb_data) > 64:
        cb_data = f"trade_short_{best_match['token']}_{best_match['lot_size']}" 
        
    btn = telebot.types.InlineKeyboardButton("⚡ Execute Trade", callback_data=cb_data)
    markup.add(btn)
    
    send_or_edit(text, markup=markup)

if bot:
    @bot.message_handler(content_types=['photo'])
    def handle_photo(message):
        chat_id = message.chat.id
        msg_id = message.message_id
        
        status_msg = bot.send_message(chat_id, "⏳ **Downloading image...**", parse_mode="Markdown", reply_to_message_id=msg_id)
        
        try:
            file_info = bot.get_file(message.photo[-1].file_id)
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info.file_path}"
            
            img_response = requests.get(file_url)
            if img_response.status_code != 200:
                bot.edit_message_text("❌ Error downloading image from Telegram.", chat_id=chat_id, message_id=status_msg.message_id)
                return
            
            bot.edit_message_text("🔍 **Extracting text (OCR)...**", chat_id=chat_id, message_id=status_msg.message_id, parse_mode="Markdown")
            
            ocr_api_key = os.getenv("OCR_SPACE_API_KEY", "helloworld")
            r = requests.post(
                "https://api.ocr.space/parse/image", 
                data={'apikey': ocr_api_key, 'isOverlayRequired': False},
                files={'file': ('image.jpg', img_response.content, 'image/jpeg')}
            )
            ocr_result = r.json()
            
            if ocr_result.get("IsErroredOnProcessing"):
                bot.edit_message_text(f"❌ OCR API Error: {ocr_result.get('ErrorMessage')}", chat_id=chat_id, message_id=status_msg.message_id)
                return
                
            parsed_text = ocr_result.get("ParsedResults", [{}])[0].get("ParsedText", "")
            
            bot.edit_message_text("🧠 **Decoding options and finding match...**", chat_id=chat_id, message_id=status_msg.message_id, parse_mode="Markdown")
            
            caption = message.caption or ""
            raw_text = caption + " " + parsed_text
            
            _process_telegram_text(raw_text, chat_id, msg_id, status_msg.message_id)
            
        except Exception as e:
            bot.edit_message_text(f"❌ Bot Error processing image: {str(e)}", chat_id=chat_id, message_id=status_msg.message_id)
            
    @bot.callback_query_handler(func=lambda call: call.data.startswith('trade_'))
    def handle_trade_callback(call):
        try:
            parts = call.data.split('_')
            if parts[1] == "short":
                token = parts[2]
                qty = parts[3]
                symbol = "Unknown"
            else:
                symbol = parts[1]
                token = parts[2]
                qty = parts[3]
                
            obj = get_session()
            df = get_instrument_df()
            opt_info = df[df["token"] == token]
            if opt_info.empty:
                 bot.answer_callback_query(call.id, "❌ Error: Could not find instrument in memory.")
                 return
                 
            real_symbol = opt_info.iloc[0]["symbol"]
            inst_type = opt_info.iloc[0]["instrumenttype"]
            
            orderparams = {
                "variety": "NORMAL",
                "tradingsymbol": real_symbol,
                "symboltoken": token,
                "transactiontype": "BUY",
                "exchange": opt_info.iloc[0]["exch_seg"],
                "ordertype": "MARKET",
                "producttype": "CARRYFORWARD",
                "duration": "DAY",
                "quantity": str(qty)
            }
            
            orderId = obj.placeOrder(orderparams)
            
            bot.answer_callback_query(call.id, "✅ Trade Executed!")
            bot.edit_message_text(
                f"{call.message.text}\n\n✅ **Trade Executed! (Order ID: {orderId})**", 
                chat_id=call.message.chat.id, 
                message_id=call.message.message_id,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ Execution Failed: {str(e)}", show_alert=True)


