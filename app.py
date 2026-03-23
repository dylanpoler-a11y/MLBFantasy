"""MLB Fantasy Auction Dashboard — Flask app."""

import csv
import json
import os
import time
import requests as http_requests
from flask import Flask, jsonify, render_template, request, redirect, session
from dotenv import load_dotenv
from fantrax_api import FantraxAPI

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "mlb-draft-dashboard-2026")

# Yahoo OAuth config
YAHOO_CLIENT_ID = os.getenv("YAHOO_CLIENT_ID", "")
YAHOO_CLIENT_SECRET = os.getenv("YAHOO_CLIENT_SECRET", "")
YAHOO_AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
YAHOO_API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
YAHOO_TOKEN_FILE = os.path.join(os.path.dirname(__file__), "yahoo_token.json")

CACHE_FILE = os.path.join(os.path.dirname(__file__), "league_cache.json")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
AUCTION_CSV = os.path.join(DATA_DIR, "auction_values.csv")
DRAFT_STATE_FILE = os.path.join(DATA_DIR, "draft_state.json")

LEAGUE_ID = os.getenv("FANTRAX_LEAGUE_ID", "b8174e3wmmus7eep")
COOKIE = os.getenv("FANTRAX_COOKIE", "")

api = FantraxAPI(LEAGUE_ID, COOKIE)


# ── Pages ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("dashboard.html", league_id=LEAGUE_ID)


# ── API Proxy Routes ──────────────────────────────────────────────────

@app.route("/api/connection")
def api_connection():
    result = api.test_connection()
    status = 200 if result["success"] else 401
    return jsonify(result), status


@app.route("/api/league")
def api_league():
    try:
        data = api.get_league_info()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/rosters")
def api_rosters():
    try:
        period = request.args.get("period", type=int)
        data = api.get_team_rosters(period)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/draft")
def api_draft():
    try:
        data = api.get_draft_picks()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/standings")
def api_standings():
    try:
        data = api.get_standings()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/players")
def api_players():
    try:
        data = api.get_player_ids()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/adp")
def api_adp():
    try:
        position = request.args.get("position")
        start = request.args.get("start", 0, type=int)
        limit = request.args.get("limit", 500, type=int)
        data = api.get_adp(position, start, limit)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/raw-league")
def api_raw_league():
    """Raw league data dump for debugging."""
    try:
        data = api.get_league_info()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cache-league", methods=["POST", "OPTIONS"])
def cache_league():
    """Accept league data pushed from the browser (bypasses cookie auth)."""
    if request.method == "OPTIONS":
        resp = app.make_default_options_response()
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)
    resp = jsonify({"success": True, "keys": list(data.keys())})
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/api/cached-league")
def cached_league():
    """Serve cached league data (no auth needed)."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return jsonify(json.load(f))
    return jsonify({"error": "No cached data"}), 404


@app.route("/api/update-cookie", methods=["POST"])
def update_cookie():
    """Update the cookie at runtime (for easy setup from the UI)."""
    global api
    body = request.get_json()
    cookie = body.get("cookie", "")
    if not cookie:
        return jsonify({"error": "No cookie provided"}), 400
    api = FantraxAPI(LEAGUE_ID, cookie)
    result = api.test_connection()
    status = 200 if result["success"] else 401
    return jsonify(result), status


def _load_auction_values():
    """Load auction values from Rotowire CSV export."""
    players = []
    if not os.path.exists(AUCTION_CSV):
        return players
    with open(AUCTION_CSV, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader)  # skip header row 1 (category labels)
        headers = next(reader)  # row 2 has column names
        for row in reader:
            if len(row) < 2 or not row[1].strip():
                continue
            player = {}
            for i, h in enumerate(headers):
                if i < len(row):
                    player[h] = row[i].strip()
            players.append(player)
    return players


@app.route("/api/auction-values")
def api_auction_values():
    """Return player auction values with optional position/search filters."""
    players = _load_auction_values()
    pos = request.args.get("pos", "").upper()
    search = request.args.get("q", "").lower()
    sort_by = request.args.get("sort", "Value")
    limit = request.args.get("limit", 100, type=int)
    offset = request.args.get("offset", 0, type=int)

    if pos and pos != "ALL":
        players = [p for p in players if pos in (p.get("Pos", "").upper().split("/"))]
    if search:
        players = [p for p in players if search in p.get("Player", "").lower()]

    # Sort
    def sort_key(p):
        try:
            return float(p.get(sort_by, 0))
        except (ValueError, TypeError):
            return 0
    players.sort(key=sort_key, reverse=True)

    total = len(players)
    players = players[offset:offset + limit]
    return jsonify({"players": players, "total": total})


# ── Draft Tracker ─────────────────────────────────────────────────────

def _load_draft_state():
    if os.path.exists(DRAFT_STATE_FILE):
        with open(DRAFT_STATE_FILE) as f:
            return json.load(f)
    return {"picks": [], "budgets": {}, "started": False}


def _save_draft_state(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DRAFT_STATE_FILE, "w") as f:
        json.dump(state, f)


@app.route("/api/draft-state")
def get_draft_state():
    return jsonify(_load_draft_state())


@app.route("/api/draft-pick", methods=["POST"])
def add_draft_pick():
    """Record an auction pick: {player, team, price}."""
    body = request.get_json()
    player = body.get("player", "")
    team = body.get("team", "")
    price = body.get("price", 0)
    if not player or not team:
        return jsonify({"error": "player and team required"}), 400
    state = _load_draft_state()
    state["picks"].append({
        "player": player, "team": team, "price": price,
        "pick_num": len(state["picks"]) + 1,
    })
    # Update team budget
    budget = state["budgets"].get(team, {"spent": 0, "players": 0})
    budget["spent"] = budget.get("spent", 0) + price
    budget["players"] = budget.get("players", 0) + 1
    state["budgets"][team] = budget
    _save_draft_state(state)
    return jsonify({"success": True, "state": state})


@app.route("/api/draft-undo", methods=["POST"])
def undo_draft_pick():
    """Undo the last draft pick."""
    state = _load_draft_state()
    if not state["picks"]:
        return jsonify({"error": "No picks to undo"}), 400
    removed = state["picks"].pop()
    team = removed["team"]
    if team in state["budgets"]:
        state["budgets"][team]["spent"] -= removed["price"]
        state["budgets"][team]["players"] -= 1
    _save_draft_state(state)
    return jsonify({"success": True, "removed": removed, "state": state})


@app.route("/api/draft-reset", methods=["POST"])
def reset_draft():
    """Reset the entire draft state."""
    _save_draft_state({"picks": [], "budgets": {}, "started": False})
    return jsonify({"success": True})


@app.route("/api/custom-rankings")
def api_custom_rankings():
    """Return custom fantasy point rankings."""
    rankings_path = os.path.join(DATA_DIR, "custom_rankings.json")
    if not os.path.exists(rankings_path):
        return jsonify({"error": "Run calc_points.py first"}), 404
    with open(rankings_path) as f:
        players = json.load(f)
    pos = request.args.get("pos", "").upper()
    ptype = request.args.get("type", "")
    search = request.args.get("q", "").lower()
    limit = request.args.get("limit", 100, type=int)

    if pos and pos != "ALL":
        players = [p for p in players if pos in p.get("pos", "").upper()]
    if ptype:
        players = [p for p in players if p.get("type", "") == ptype]
    if search:
        players = [p for p in players if search in p.get("player", "").lower()]

    return jsonify({"players": players[:limit], "total": len(players)})


@app.route("/api/draft-plans")
def api_draft_plans():
    """Return draft plans markdown."""
    plans_path = os.path.join(DATA_DIR, "draft_plans.md")
    if not os.path.exists(plans_path):
        return jsonify({"error": "Draft plans not generated yet"}), 404
    with open(plans_path) as f:
        return jsonify({"content": f.read()})


PLAN_DATA_FILE = os.path.join(DATA_DIR, "draft_plans_data.json")
PLAN_STATE_FILE = os.path.join(DATA_DIR, "draft_plan_state.json")


@app.route("/api/draft-plans-data")
def api_draft_plans_data():
    """Return structured draft plan data with alternatives."""
    if not os.path.exists(PLAN_DATA_FILE):
        return jsonify({"error": "Plan data not generated yet"}), 404
    with open(PLAN_DATA_FILE) as f:
        return jsonify(json.load(f))


@app.route("/api/draft-plan-state")
def get_plan_state():
    """Return the interactive plan state."""
    if os.path.exists(PLAN_STATE_FILE):
        with open(PLAN_STATE_FILE) as f:
            return jsonify(json.load(f))
    return jsonify({"active_plan": "A", "slots": {}})


@app.route("/api/draft-plan-state", methods=["POST"])
def save_plan_state():
    """Save the interactive plan state."""
    body = request.get_json()
    if not body:
        return jsonify({"error": "No data"}), 400
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PLAN_STATE_FILE, "w") as f:
        json.dump(body, f)
    return jsonify({"success": True})


# ── Mock Draft ────────────────────────────────────────────────────────

MOCK_DRAFTS_DIR = os.path.join(DATA_DIR, "mock_drafts")


@app.route("/api/mock-draft/players")
def mock_draft_players():
    """Return the player pool for mock drafts."""
    rankings_path = os.path.join(DATA_DIR, "custom_rankings.json")
    if not os.path.exists(rankings_path):
        return jsonify({"error": "Run calc_points.py first"}), 404
    with open(rankings_path) as f:
        players = json.load(f)
    # Ensure all players have a reasonable auction value
    for p in players:
        val = float(p.get("auction_value", 0))
        if val <= 0:
            fpts = float(p.get("fpts", 0))
            if fpts >= 680:
                val = 40
            elif fpts >= 600:
                val = 30
            elif fpts >= 550:
                val = 20
            elif fpts >= 500:
                val = 14
            elif fpts >= 450:
                val = 8
            elif fpts >= 400:
                val = 4
            elif fpts >= 350:
                val = 2
            else:
                val = 1
            p["auction_value"] = str(val)
    return jsonify({"players": players})


@app.route("/api/mock-draft/sessions")
def list_mock_sessions():
    """List all saved mock draft sessions."""
    os.makedirs(MOCK_DRAFTS_DIR, exist_ok=True)
    sessions = []
    for fname in sorted(os.listdir(MOCK_DRAFTS_DIR), reverse=True):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(MOCK_DRAFTS_DIR, fname)
        try:
            with open(fpath) as f:
                data = json.load(f)
            sessions.append({
                "id": fname.replace(".json", ""),
                "name": data.get("name", "Untitled"),
                "plan": data.get("activePlan", "?"),
                "picks": data.get("pickNum", 0),
                "status": data.get("status", "in_progress"),
                "savedAt": data.get("savedAt", ""),
                "userFpts": data.get("userFpts", 0),
                "userSpent": data.get("userSpent", 0),
            })
        except Exception:
            continue
    return jsonify({"sessions": sessions})


@app.route("/api/mock-draft/sessions/<session_id>", methods=["GET"])
def get_mock_session(session_id):
    """Load a specific saved mock draft session."""
    fpath = os.path.join(MOCK_DRAFTS_DIR, session_id + ".json")
    if not os.path.exists(fpath):
        return jsonify({"error": "Session not found"}), 404
    with open(fpath) as f:
        return jsonify(json.load(f))


@app.route("/api/mock-draft/sessions", methods=["POST"])
def save_mock_session():
    """Save a mock draft session (new or update)."""
    body = request.get_json()
    if not body:
        return jsonify({"error": "No data"}), 400
    os.makedirs(MOCK_DRAFTS_DIR, exist_ok=True)
    session_id = body.get("id") or f"mock_{int(time.time())}"
    body["id"] = session_id
    body["savedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
    fpath = os.path.join(MOCK_DRAFTS_DIR, session_id + ".json")
    with open(fpath, "w") as f:
        json.dump(body, f)
    return jsonify({"success": True, "id": session_id})


@app.route("/api/mock-draft/sessions/<session_id>", methods=["DELETE"])
def delete_mock_session(session_id):
    """Delete a saved mock draft session."""
    fpath = os.path.join(MOCK_DRAFTS_DIR, session_id + ".json")
    if os.path.exists(fpath):
        os.remove(fpath)
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404


# ── Live Draft Sync ───────────────────────────────────────────────────

LIVE_DRAFT_FILE = os.path.join(DATA_DIR, "live_draft.json")


def _load_live_draft():
    if os.path.exists(LIVE_DRAFT_FILE):
        with open(LIVE_DRAFT_FILE) as f:
            return json.load(f)
    return {"picks": [], "teams": {}, "status": "not_started", "lastSync": ""}


def _save_live_draft(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LIVE_DRAFT_FILE, "w") as f:
        json.dump(state, f)


@app.route("/api/yahoo-draft-results")
def get_yahoo_draft_results():
    """Return Yahoo mock draft results from static JSON."""
    path = os.path.join(DATA_DIR, "yahoo_draft_results.json")
    if os.path.exists(path):
        with open(path) as f:
            return jsonify(json.load(f))
    return jsonify({"error": "No Yahoo draft results found"}), 404


@app.route("/api/live-draft")
def get_live_draft():
    """Get current live draft state."""
    return jsonify(_load_live_draft())


@app.route("/api/live-draft/pick", methods=["POST"])
def add_live_pick():
    """Add a pick from Chrome scraping or manual entry.
    Body: {player, team, price, pos (optional)}
    """
    body = request.get_json()
    if not body or not body.get("player"):
        return jsonify({"error": "player required"}), 400
    state = _load_live_draft()
    state["status"] = "in_progress"

    # Check for duplicate
    existing = [p for p in state["picks"] if p["player"] == body["player"]]
    if existing:
        return jsonify({"error": f"{body['player']} already drafted", "duplicate": True})

    pick = {
        "player": body["player"],
        "team": body.get("team", "Unknown"),
        "price": body.get("price", 1),
        "pos": body.get("pos", ""),
        "pick_num": len(state["picks"]) + 1,
        "timestamp": time.strftime("%H:%M:%S"),
        "is_user": body.get("is_user", False),
    }
    state["picks"].append(pick)
    state["lastSync"] = time.strftime("%Y-%m-%d %H:%M:%S")

    # Update team budgets
    team = pick["team"]
    if team not in state["teams"]:
        state["teams"][team] = {"spent": 0, "players": 0, "roster": []}
    state["teams"][team]["spent"] += pick["price"]
    state["teams"][team]["players"] += 1
    state["teams"][team]["roster"].append(pick["player"])

    _save_live_draft(state)
    return jsonify({"success": True, "pick": pick, "total_picks": len(state["picks"])})


@app.route("/api/live-draft/bulk", methods=["POST"])
def bulk_live_picks():
    """Add multiple picks at once (from Chrome scrape).
    Body: {picks: [{player, team, price, pos}, ...]}
    """
    body = request.get_json()
    if not body or not body.get("picks"):
        return jsonify({"error": "picks array required"}), 400

    state = _load_live_draft()
    state["status"] = "in_progress"
    existing_names = {p["player"] for p in state["picks"]}
    added = 0

    for pick_data in body["picks"]:
        if pick_data["player"] in existing_names:
            continue
        pick = {
            "player": pick_data["player"],
            "team": pick_data.get("team", "Unknown"),
            "price": pick_data.get("price", 1),
            "pos": pick_data.get("pos", ""),
            "pick_num": len(state["picks"]) + 1,
            "timestamp": time.strftime("%H:%M:%S"),
            "is_user": pick_data.get("is_user", False),
        }
        state["picks"].append(pick)
        existing_names.add(pick["player"])

        team = pick["team"]
        if team not in state["teams"]:
            state["teams"][team] = {"spent": 0, "players": 0, "roster": []}
        state["teams"][team]["spent"] += pick["price"]
        state["teams"][team]["players"] += 1
        state["teams"][team]["roster"].append(pick["player"])
        added += 1

    state["lastSync"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_live_draft(state)
    return jsonify({"success": True, "added": added, "total_picks": len(state["picks"])})


@app.route("/api/live-draft/undo", methods=["POST"])
def undo_live_pick():
    """Undo the last live draft pick."""
    state = _load_live_draft()
    if not state["picks"]:
        return jsonify({"error": "No picks to undo"}), 400
    removed = state["picks"].pop()
    team = removed["team"]
    if team in state["teams"]:
        state["teams"][team]["spent"] -= removed["price"]
        state["teams"][team]["players"] -= 1
        if removed["player"] in state["teams"][team]["roster"]:
            state["teams"][team]["roster"].remove(removed["player"])
    _save_live_draft(state)
    return jsonify({"success": True, "removed": removed})


@app.route("/api/live-draft/reset", methods=["POST"])
def reset_live_draft():
    """Reset live draft."""
    _save_live_draft({"picks": [], "teams": {}, "status": "not_started", "lastSync": ""})
    return jsonify({"success": True})


@app.route("/api/live-draft/quick-entry", methods=["POST"])
def quick_entry():
    """Quick manual entry: 'Skubal 46 TeamName' or just 'Skubal 46'.
    Body: {text: 'player_name price [team]'}
    """
    body = request.get_json()
    text = body.get("text", "").strip()
    if not text:
        return jsonify({"error": "No text"}), 400

    # Parse: "Player Name $46 Team Name" or "Player Name 46 Team"
    import re
    # Try to match price
    price_match = re.search(r'\$?(\d+)', text)
    if not price_match:
        return jsonify({"error": "Could not find a price. Format: 'Player Name $46 Team'"}), 400

    price = int(price_match.group(1))
    before_price = text[:price_match.start()].strip()
    after_price = text[price_match.end():].strip()

    # Player name is before price, team is after (or "Other" if not specified)
    player_name = before_price or after_price
    team_name = after_price if before_price else "Unknown"

    if not player_name:
        return jsonify({"error": "Could not find player name"}), 400

    # Try fuzzy match against player pool
    rankings_path = os.path.join(DATA_DIR, "custom_rankings.json")
    matched_player = player_name
    matched_pos = ""
    if os.path.exists(rankings_path):
        with open(rankings_path) as f:
            players = json.load(f)
        # Exact match first
        exact = [p for p in players if p["player"].lower() == player_name.lower()]
        if exact:
            matched_player = exact[0]["player"]
            matched_pos = exact[0].get("pos", "")
        else:
            # Partial match
            partial = [p for p in players if player_name.lower() in p["player"].lower()]
            if len(partial) == 1:
                matched_player = partial[0]["player"]
                matched_pos = partial[0].get("pos", "")
            elif len(partial) > 1:
                # Return suggestions
                suggestions = [p["player"] for p in partial[:5]]
                return jsonify({"error": "Multiple matches", "suggestions": suggestions}), 400

    # Add the pick
    state = _load_live_draft()
    state["status"] = "in_progress"

    # Check duplicate
    if any(p["player"] == matched_player for p in state["picks"]):
        return jsonify({"error": f"{matched_player} already drafted"}), 400

    pick = {
        "player": matched_player,
        "team": team_name,
        "price": price,
        "pos": matched_pos,
        "pick_num": len(state["picks"]) + 1,
        "timestamp": time.strftime("%H:%M:%S"),
        "is_user": False,
    }
    state["picks"].append(pick)
    state["lastSync"] = time.strftime("%Y-%m-%d %H:%M:%S")

    team = pick["team"]
    if team not in state["teams"]:
        state["teams"][team] = {"spent": 0, "players": 0, "roster": []}
    state["teams"][team]["spent"] += pick["price"]
    state["teams"][team]["players"] += 1
    state["teams"][team]["roster"].append(pick["player"])

    _save_live_draft(state)
    return jsonify({"success": True, "pick": pick})


# ── Yahoo Fantasy API ─────────────────────────────────────────────────

def _save_yahoo_token(token_data):
    """Save Yahoo OAuth token to file."""
    token_data["saved_at"] = time.time()
    with open(YAHOO_TOKEN_FILE, "w") as f:
        json.dump(token_data, f)


def _load_yahoo_token():
    """Load Yahoo OAuth token from file."""
    if not os.path.exists(YAHOO_TOKEN_FILE):
        return None
    with open(YAHOO_TOKEN_FILE) as f:
        return json.load(f)


def _refresh_yahoo_token(token_data):
    """Refresh an expired Yahoo OAuth token."""
    resp = http_requests.post(YAHOO_TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": token_data["refresh_token"],
        "redirect_uri": "https://localhost:5050/yahoo/callback",
        "client_id": YAHOO_CLIENT_ID,
        "client_secret": YAHOO_CLIENT_SECRET,
    })
    if resp.status_code == 200:
        new_token = resp.json()
        new_token["refresh_token"] = token_data.get("refresh_token", new_token.get("refresh_token"))
        _save_yahoo_token(new_token)
        return new_token
    return None


def _get_yahoo_token():
    """Get a valid Yahoo token, refreshing if needed."""
    token = _load_yahoo_token()
    if not token:
        return None
    # Check if expired (tokens last 3600s)
    elapsed = time.time() - token.get("saved_at", 0)
    if elapsed > 3500:
        token = _refresh_yahoo_token(token)
    return token


def _yahoo_api(endpoint, params=None):
    """Make a Yahoo Fantasy API call."""
    token = _get_yahoo_token()
    if not token:
        return {"error": "Not authenticated. Visit /yahoo/login first."}
    headers = {
        "Authorization": f"Bearer {token['access_token']}",
        "Accept": "application/json",
    }
    url = f"{YAHOO_API_BASE}{endpoint}"
    resp = http_requests.get(url, headers=headers, params=params or {})
    if resp.status_code == 401:
        # Try refresh
        token = _refresh_yahoo_token(token)
        if token:
            headers["Authorization"] = f"Bearer {token['access_token']}"
            resp = http_requests.get(url, headers=headers, params=params or {})
    if resp.status_code == 200:
        return resp.json()
    return {"error": f"Yahoo API error {resp.status_code}", "body": resp.text[:500]}


@app.route("/yahoo/login")
def yahoo_login():
    """Redirect to Yahoo OAuth login."""
    if not YAHOO_CLIENT_ID:
        return "YAHOO_CLIENT_ID not set in .env", 500
    auth_url = (
        f"{YAHOO_AUTH_URL}?client_id={YAHOO_CLIENT_ID}"
        f"&redirect_uri=https://localhost:5050/yahoo/callback"
        f"&response_type=code"
        f"&language=en-us"
    )
    return redirect(auth_url)


@app.route("/yahoo/callback")
def yahoo_callback():
    """Handle Yahoo OAuth callback."""
    code = request.args.get("code")
    if not code:
        return "No auth code received", 400
    # Exchange code for token
    resp = http_requests.post(YAHOO_TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://localhost:5050/yahoo/callback",
        "client_id": YAHOO_CLIENT_ID,
        "client_secret": YAHOO_CLIENT_SECRET,
    })
    if resp.status_code != 200:
        return f"Token exchange failed: {resp.text}", 500
    token_data = resp.json()
    _save_yahoo_token(token_data)
    return redirect("/?yahoo=connected")


@app.route("/api/yahoo/status")
def yahoo_status():
    """Check if Yahoo is connected."""
    token = _get_yahoo_token()
    if token:
        return jsonify({"connected": True})
    return jsonify({"connected": False})


@app.route("/api/yahoo/leagues")
def yahoo_leagues():
    """Get user's Yahoo fantasy baseball leagues."""
    data = _yahoo_api("/users;use_login=1/games;game_keys=mlb/leagues", {"format": "json"})
    return jsonify(data)


@app.route("/api/yahoo/league/<league_key>/draft")
def yahoo_draft_results(league_key):
    """Get draft results for a Yahoo league."""
    data = _yahoo_api(f"/league/{league_key}/draftresults", {"format": "json"})
    return jsonify(data)


@app.route("/api/yahoo/league/<league_key>/players")
def yahoo_players(league_key):
    """Get players in a Yahoo league."""
    start = request.args.get("start", 0, type=int)
    data = _yahoo_api(f"/league/{league_key}/players;start={start};count=25", {"format": "json"})
    return jsonify(data)


@app.route("/api/yahoo/league/<league_key>/teams")
def yahoo_teams(league_key):
    """Get teams in a Yahoo league."""
    data = _yahoo_api(f"/league/{league_key}/teams", {"format": "json"})
    return jsonify(data)


@app.route("/api/yahoo/league/<league_key>/transactions")
def yahoo_transactions(league_key):
    """Get recent transactions (includes draft picks in auction)."""
    data = _yahoo_api(f"/league/{league_key}/transactions;types=add", {"format": "json"})
    return jsonify(data)


if __name__ == "__main__":
    app.run(debug=True, port=5050)
