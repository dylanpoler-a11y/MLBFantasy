"""MLB Fantasy Auction Dashboard — Flask app."""

import os
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv
from fantrax_api import FantraxAPI

load_dotenv()

app = Flask(__name__)

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


if __name__ == "__main__":
    app.run(debug=True, port=5000)
