#!/usr/bin/env python3
"""Build a static version of the dashboard for GitHub Pages deployment.

Replaces:
- Jinja template variables with hardcoded values
- /static/ paths with static/ (relative)
- Injects a fetch interceptor that redirects API calls to static JSON files + localStorage
"""

import json
import os
import shutil

BASE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(BASE, "docs")
DATA = os.path.join(BASE, "data")

# Ensure dirs exist
os.makedirs(os.path.join(DOCS, "data"), exist_ok=True)
os.makedirs(os.path.join(DOCS, "static"), exist_ok=True)

# Copy static assets
shutil.copy2(os.path.join(BASE, "static", "style.css"), os.path.join(DOCS, "static", "style.css"))

# Copy data files
for f in ["draft_plans_data.json", "custom_rankings.json", "draft_plans.md"]:
    src = os.path.join(DATA, f)
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(DOCS, "data", f))

# Pre-process custom_rankings.json to add auction values for pitchers
rankings_path = os.path.join(DOCS, "data", "custom_rankings.json")
with open(rankings_path) as f:
    players = json.load(f)
for p in players:
    val = float(p.get("auction_value", 0))
    if val <= 0:
        fpts = float(p.get("fpts", 0))
        if fpts >= 680: val = 40
        elif fpts >= 600: val = 30
        elif fpts >= 550: val = 20
        elif fpts >= 500: val = 14
        elif fpts >= 450: val = 8
        elif fpts >= 400: val = 4
        elif fpts >= 350: val = 2
        else: val = 1
        p["auction_value"] = str(val)
with open(rankings_path, "w") as f:
    json.dump(players, f)

# Read template
with open(os.path.join(BASE, "templates", "dashboard.html")) as f:
    html = f.read()

# Replace Jinja variables
LEAGUE_ID = os.getenv("FANTRAX_LEAGUE_ID", "b8174e3wmmus7eep")
html = html.replace("{{ league_id }}", LEAGUE_ID)

# Fix static asset path (absolute -> relative)
html = html.replace('href="/static/style.css"', 'href="static/style.css"')

# Inject the fetch interceptor right after <head> opening
FETCH_INTERCEPTOR = '''
<script>
// ── Static Site Fetch Interceptor ──
// Redirects Flask API calls to static JSON files + localStorage
(function() {
    const _originalFetch = window.fetch;
    window.fetch = function(url, options) {
        const method = (options && options.method || 'GET').toUpperCase();
        const urlStr = typeof url === 'string' ? url : url.toString();

        // GET /api/connection → always connected with static data
        if (urlStr === '/api/connection') {
            return Promise.resolve(new Response(JSON.stringify({success: true, mode: "static", data: {leagueName: "Fantasia Hebraica", numTeams: 12, _static: true}}), {status: 200, headers: {'Content-Type': 'application/json'}}));
        }

        // GET /api/cached-league → return static league info
        if (urlStr === '/api/cached-league') {
            return Promise.resolve(new Response(JSON.stringify({leagueName: "Fantasia Hebraica", numTeams: 12, _static: true}), {status: 200, headers: {'Content-Type': 'application/json'}}));
        }

        // GET /api/draft-plans-data → static file
        if (urlStr === '/api/draft-plans-data' && method === 'GET') {
            return _originalFetch('data/draft_plans_data.json');
        }

        // GET /api/draft-plans → static markdown
        if (urlStr === '/api/draft-plans' && method === 'GET') {
            return _originalFetch('data/draft_plans.md').then(r => r.text()).then(text => {
                return new Response(JSON.stringify({content: text}), {status: 200, headers: {'Content-Type': 'application/json'}});
            });
        }

        // GET /api/draft-plan-state → localStorage
        if (urlStr === '/api/draft-plan-state' && method === 'GET') {
            const state = localStorage.getItem('mlb_plan_state');
            if (state) {
                return Promise.resolve(new Response(state, {status: 200, headers: {'Content-Type': 'application/json'}}));
            }
            return Promise.resolve(new Response(JSON.stringify({active_plan: "A", slots: {}}), {status: 200, headers: {'Content-Type': 'application/json'}}));
        }

        // POST /api/draft-plan-state → localStorage
        if (urlStr === '/api/draft-plan-state' && method === 'POST') {
            const body = options && options.body;
            if (body) localStorage.setItem('mlb_plan_state', typeof body === 'string' ? body : JSON.stringify(body));
            return Promise.resolve(new Response(JSON.stringify({success: true}), {status: 200, headers: {'Content-Type': 'application/json'}}));
        }

        // GET /api/mock-draft/players → static file
        if (urlStr === '/api/mock-draft/players' && method === 'GET') {
            return _originalFetch('data/custom_rankings.json').then(r => r.json()).then(players => {
                return new Response(JSON.stringify({players: players}), {status: 200, headers: {'Content-Type': 'application/json'}});
            });
        }

        // ── Mock Draft Sessions (localStorage) ──

        // GET /api/mock-draft/sessions → list all
        if (urlStr === '/api/mock-draft/sessions' && method === 'GET') {
            const sessions = JSON.parse(localStorage.getItem('mlb_mock_sessions') || '{}');
            const list = Object.values(sessions).sort((a, b) => (b.savedAt || '').localeCompare(a.savedAt || '')).map(s => ({
                id: s.id, name: s.name || 'Untitled', plan: s.activePlan || '?',
                picks: s.pickNum || 0, status: s.status || 'in_progress',
                savedAt: s.savedAt || '', userFpts: s.userFpts || 0, userSpent: s.userSpent || 0
            }));
            return Promise.resolve(new Response(JSON.stringify({sessions: list}), {status: 200, headers: {'Content-Type': 'application/json'}}));
        }

        // POST /api/mock-draft/sessions → save
        if (urlStr === '/api/mock-draft/sessions' && method === 'POST') {
            const body = JSON.parse(options.body);
            const id = body.id || 'mock_' + Date.now();
            body.id = id;
            body.savedAt = new Date().toISOString().replace('T', ' ').substring(0, 19);
            const sessions = JSON.parse(localStorage.getItem('mlb_mock_sessions') || '{}');
            sessions[id] = body;
            localStorage.setItem('mlb_mock_sessions', JSON.stringify(sessions));
            return Promise.resolve(new Response(JSON.stringify({success: true, id: id}), {status: 200, headers: {'Content-Type': 'application/json'}}));
        }

        // GET /api/mock-draft/sessions/:id → load specific
        const loadMatch = urlStr.match(/\\/api\\/mock-draft\\/sessions\\/([^/]+)$/);
        if (loadMatch && method === 'GET') {
            const sessions = JSON.parse(localStorage.getItem('mlb_mock_sessions') || '{}');
            const session = sessions[loadMatch[1]];
            if (session) {
                return Promise.resolve(new Response(JSON.stringify(session), {status: 200, headers: {'Content-Type': 'application/json'}}));
            }
            return Promise.resolve(new Response(JSON.stringify({error: 'Not found'}), {status: 404, headers: {'Content-Type': 'application/json'}}));
        }

        // DELETE /api/mock-draft/sessions/:id → delete
        const delMatch = urlStr.match(/\\/api\\/mock-draft\\/sessions\\/([^/]+)$/);
        if (delMatch && method === 'DELETE') {
            const sessions = JSON.parse(localStorage.getItem('mlb_mock_sessions') || '{}');
            delete sessions[delMatch[1]];
            localStorage.setItem('mlb_mock_sessions', JSON.stringify(sessions));
            return Promise.resolve(new Response(JSON.stringify({success: true}), {status: 200, headers: {'Content-Type': 'application/json'}}));
        }

        // Fallback: pass through
        return _originalFetch(url, options);
    };
})();
</script>
'''

html = html.replace('<head>\n    <meta charset="UTF-8">', '<head>\n    <meta charset="UTF-8">' + FETCH_INTERCEPTOR)

# Write output
output_path = os.path.join(DOCS, "index.html")
with open(output_path, "w") as f:
    f.write(html)

print(f"✅ Built static site in {DOCS}/")
print(f"   index.html: {len(html):,} chars")
print(f"   data/: {len(os.listdir(os.path.join(DOCS, 'data')))} files")
print(f"   static/: {len(os.listdir(os.path.join(DOCS, 'static')))} files")
