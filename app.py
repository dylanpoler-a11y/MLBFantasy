"""MLB Fantasy Auction Dashboard — Flask app."""

import csv
import json
import os
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv
from fantrax_api import FantraxAPI

load_dotenv()

app = Flask(__name__)

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


if __name__ == "__main__":
    app.run(debug=True, port=5050)
