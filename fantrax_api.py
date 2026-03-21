"""Fantrax API client with cookie-based authentication for private leagues."""

import requests


BASE_URL = "https://www.fantrax.com/fxea/general"


class FantraxAPI:
    def __init__(self, league_id, cookie=None):
        self.league_id = league_id
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.fantrax.com/",
        })
        if cookie:
            self.session.headers["Cookie"] = cookie

    def _get(self, endpoint, params=None):
        if params is None:
            params = {}
        resp = self.session.get(f"{BASE_URL}/{endpoint}", params=params)
        resp.raise_for_status()
        return resp.json()

    def _post(self, endpoint, json_data=None):
        resp = self.session.post(f"{BASE_URL}/{endpoint}", json=json_data)
        resp.raise_for_status()
        return resp.json()

    def get_league_info(self):
        return self._get("getLeagueInfo", {"leagueId": self.league_id})

    def get_team_rosters(self, period=None):
        params = {"leagueId": self.league_id}
        if period is not None:
            params["period"] = period
        return self._get("getTeamRosters", params)

    def get_draft_picks(self):
        return self._get("getDraftPicks", {"leagueId": self.league_id})

    def get_standings(self):
        return self._get("getStandings", {"leagueId": self.league_id})

    def get_player_ids(self):
        return self._get("getPlayerIds", {"sport": "MLB"})

    def get_adp(self, position=None, start=0, limit=500):
        data = {"sport": "MLB", "start": start, "limit": limit}
        if position:
            data["position"] = position
        return self._post("getAdp", data)

    def test_connection(self):
        """Test if we can reach the league. Returns league info or error details."""
        try:
            info = self.get_league_info()
            return {"success": True, "data": info}
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                return {
                    "success": False,
                    "error": "Authentication required. Please set your FANTRAX_COOKIE in .env",
                    "status": 403,
                }
            return {"success": False, "error": str(e), "status": e.response.status_code}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Could not connect to Fantrax"}
