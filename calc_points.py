"""Calculate custom fantasy points for Fantasia Hebraica league scoring."""
import csv
import json
import os

# League scoring weights
HITTING_SCORING = {
    "R": 2, "RBI": 2, "HR": 1.5, "SB": 1.5, "H": 1, "BB": 1,
    "3B": 1, "2B": 0.5, "SO": -0.35, "CS": -1.5,
}

PITCHING_SCORING = {
    "SV": 5, "W": 4, "IP": 2.25, "QS": 1.5, "K": 1.5, "GS": 1,
    "H_allowed": -0.17, "BB_allowed": -0.17, "HR_allowed": -0.5,
    "HB": -1, "ER": -2.5, "L": -4,
}

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def calc_hitter_points(p):
    """Calculate projected fantasy points for a hitter from auction CSV."""
    try:
        g = float(p.get("G", 0) or 0)
        ab = float(p.get("AB", 0) or 0)
        avg = float(p.get("AVG", ".000").replace(",", "") or 0)
        hr = float(p.get("HR", 0) or 0)
        rbi = float(p.get("RBI", 0) or 0)
        sb = float(p.get("SB", 0) or 0)
        r = float(p.get("R", 0) or 0)

        # Estimate component stats from available data
        hits = ab * avg if ab > 0 else 0
        # Rough estimates for missing granular stats
        doubles = hits * 0.18  # ~18% of hits are doubles
        triples = hits * 0.02  # ~2% of hits are triples
        singles = hits - doubles - triples - hr
        bb = ab * 0.08  # estimate walks from AB
        so = ab * 0.22  # estimate strikeouts from AB
        cs = sb * 0.25  # estimate CS from SB

        pts = (
            r * HITTING_SCORING["R"] +
            rbi * HITTING_SCORING["RBI"] +
            hr * HITTING_SCORING["HR"] +
            sb * HITTING_SCORING["SB"] +
            hits * HITTING_SCORING["H"] +
            bb * HITTING_SCORING["BB"] +
            triples * HITTING_SCORING["3B"] +
            doubles * HITTING_SCORING["2B"] +
            so * HITTING_SCORING["SO"] +
            cs * HITTING_SCORING["CS"]
        )
        return round(pts, 1)
    except (ValueError, TypeError):
        return 0


def calc_pitcher_points(p):
    """Calculate projected fantasy points for a pitcher from pitcher projections CSV."""
    try:
        ip = float(p.get("IP", 0) or 0)
        w = float(p.get("W", 0) or 0)
        l = float(p.get("L", 0) or 0)
        sv = float(p.get("SV", 0) or 0)
        k = float(p.get("K", 0) or 0)
        h = float(p.get("H", 0) or 0)
        hr = float(p.get("HR", 0) or 0)
        bb = float(p.get("BB", 0) or 0)
        er = float(p.get("ER", 0) or 0)
        gs = float(p.get("GS", 0) or 0)
        qs = float(p.get("QS", 0) or 0)
        hld = float(p.get("HLD", 0) or 0)

        # HB (hit batsmen) not in the CSV, estimate ~2% of BB
        hb = bb * 0.3

        pts = (
            sv * PITCHING_SCORING["SV"] +
            w * PITCHING_SCORING["W"] +
            ip * PITCHING_SCORING["IP"] +
            qs * PITCHING_SCORING["QS"] +
            k * PITCHING_SCORING["K"] +
            gs * PITCHING_SCORING["GS"] +
            h * PITCHING_SCORING["H_allowed"] +
            bb * PITCHING_SCORING["BB_allowed"] +
            hr * PITCHING_SCORING["HR_allowed"] +
            hb * PITCHING_SCORING["HB"] +
            er * PITCHING_SCORING["ER"] +
            l * PITCHING_SCORING["L"]
        )
        return round(pts, 1)
    except (ValueError, TypeError):
        return 0


def main():
    # Load hitter data from auction values CSV
    hitters = []
    auction_path = os.path.join(DATA_DIR, "auction_values.csv")
    with open(auction_path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader)  # skip header row 1
        headers = next(reader)  # row 2
        for row in reader:
            if len(row) < 2 or not row[1].strip():
                continue
            p = {h: row[i].strip() for i, h in enumerate(headers) if i < len(row)}
            pos = p.get("Pos", "")
            ab = float(p.get("AB", 0) or 0)
            if ab > 0:  # is a hitter (or two-way)
                p["fpts"] = calc_hitter_points(p)
                p["type"] = "hitter"
                hitters.append(p)

    # Load pitcher data
    pitchers = []
    pitcher_path = os.path.join(DATA_DIR, "pitcher_projections.csv")
    with open(pitcher_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for p in reader:
            ip = float(p.get("IP", 0) or 0)
            if ip >= 10:  # meaningful playing time
                p["fpts"] = calc_pitcher_points(p)
                p["type"] = "pitcher"
                p["Pos"] = "SP" if float(p.get("GS", 0) or 0) > 5 else "RP"
                p["Age"] = ""
                pitchers.append(p)

    # Also calculate pitching points for two-way players in auction CSV
    two_way = []
    with open(auction_path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader)
        headers = next(reader)
        for row in reader:
            if len(row) < 2 or not row[1].strip():
                continue
            p = {h: row[i].strip() for i, h in enumerate(headers) if i < len(row)}
            ip = float(p.get("IP", "0") or 0)
            ab = float(p.get("AB", "0") or 0)
            if ip > 0 and ab > 0:  # two-way
                pitch_pts = ip * 2.25  # simplified
                hit_pts = calc_hitter_points(p)
                p["fpts"] = round(hit_pts + pitch_pts, 1)
                p["type"] = "two-way"
                p["note"] = f"Hit:{hit_pts} + Pitch(est):{round(pitch_pts,1)}"

    # Sort all by fantasy points
    hitters.sort(key=lambda x: x["fpts"], reverse=True)
    pitchers.sort(key=lambda x: x["fpts"], reverse=True)

    # Build combined rankings
    all_players = []

    # Add top hitters
    for i, p in enumerate(hitters[:300]):
        all_players.append({
            "rank": 0,
            "player": p.get("Player", ""),
            "team": p.get("Team", ""),
            "pos": p.get("Pos", ""),
            "age": p.get("Age", ""),
            "fpts": p["fpts"],
            "auction_value": p.get("Value", "0"),
            "type": "hitter",
            "hr": p.get("HR", "0"),
            "rbi": p.get("RBI", "0"),
            "r": p.get("R", "0"),
            "sb": p.get("SB", "0"),
            "avg": p.get("AVG", ""),
        })

    # Add top pitchers
    for i, p in enumerate(pitchers[:400]):
        all_players.append({
            "rank": 0,
            "player": p.get("Player", ""),
            "team": p.get("Team", ""),
            "pos": p.get("Pos", ""),
            "age": p.get("Age", ""),
            "fpts": p["fpts"],
            "auction_value": "0",
            "type": "pitcher",
            "w": p.get("W", "0"),
            "k": p.get("K", "0"),
            "sv": p.get("SV", "0"),
            "ip": p.get("IP", "0"),
            "era": p.get("ERA", ""),
            "qs": p.get("QS", "0"),
        })

    # Sort combined by fpts
    all_players.sort(key=lambda x: x["fpts"], reverse=True)
    for i, p in enumerate(all_players):
        p["rank"] = i + 1

    # Save
    output_path = os.path.join(DATA_DIR, "custom_rankings.json")
    with open(output_path, "w") as f:
        json.dump(all_players, f, indent=2)

    print(f"Generated {len(all_players)} custom rankings")
    print(f"\nTop 20 Overall (Fantasy Points):")
    print(f"{'Rank':>4} {'Player':<25} {'Pos':<8} {'Team':<5} {'FPts':>7} {'$Value':>7}")
    print("-" * 65)
    for p in all_players[:20]:
        val = f"${float(p['auction_value']):.0f}" if float(p.get('auction_value', 0)) > 0 else "—"
        print(f"{p['rank']:>4} {p['player']:<25} {p['pos']:<8} {p['team']:<5} {p['fpts']:>7.1f} {val:>7}")

    print(f"\nTop 15 Pitchers:")
    print(f"{'Rank':>4} {'Player':<25} {'Pos':<4} {'Team':<5} {'FPts':>7} {'W':>3} {'K':>4} {'SV':>3} {'QS':>3} {'IP':>6}")
    print("-" * 70)
    pitcher_ranks = [p for p in all_players if p["type"] == "pitcher"]
    for p in pitcher_ranks[:15]:
        print(f"{p['rank']:>4} {p['player']:<25} {p['pos']:<4} {p['team']:<5} {p['fpts']:>7.1f} {p.get('w',''):>3} {p.get('k',''):>4} {p.get('sv',''):>3} {p.get('qs',''):>3} {p.get('ip',''):>6}")

    print(f"\nTop 10 Closers (by SV):")
    closers = [p for p in pitcher_ranks if float(p.get("sv", 0) or 0) >= 15]
    closers.sort(key=lambda x: x["fpts"], reverse=True)
    for p in closers[:10]:
        print(f"{p['rank']:>4} {p['player']:<25} {p['team']:<5} {p['fpts']:>7.1f} {p.get('sv',''):>3}SV {p.get('k',''):>4}K")


if __name__ == "__main__":
    main()
