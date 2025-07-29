import argparse
import json
import os
import re
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def dump(obj, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print(f"wrote {path}")

def period_name(p):
    return {
        1: "first half",
        2: "second half",
        3: "first half extratime",
        4: "second half extratime",
        5: "shootout",
    }.get(p, "unknown")

def is_goal(ev):
    return ev["type"]["name"] == "Shot" and ev["shot"]["outcome"]["name"] == "Goal"

def match_clock(ev):
    """Absolute match‑clock 'HH:MM:SS.mmm' from minute/second."""
    minute = ev.get("minute", 0) or 0
    second = ev.get("second", 0) or 0
    frac = "000"
    ts = ev.get("timestamp", "00:00:00.000")
    if "." in ts:
        frac = ts.rsplit(".", 1)[1][:3].ljust(3, "0")
    tot_sec = minute * 60 + int(second)
    hh, rem = divmod(tot_sec, 3600)
    mm, ss = divmod(rem, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}.{frac}"


def build_match_sheet(events, lineup, match_id, matches_file=None):
    ids = {t["team_id"]: t for t in lineup}
    home_id, away_id = list(ids)

    # Assist lookup
    assist_for = {}
    for ev in events:
        if ev["type"]["name"] == "Pass" and ev.get("pass", {}).get("goal_assist"):
            sid = ev["pass"].get("assisted_shot_id")
            if sid:
                assist_for[sid] = ev["player"]["id"]
    for ev in events:
        if ev["type"]["name"] == "Shot":
            kp = ev.get("shot", {}).get("key_pass_id")
            if kp and kp not in assist_for:
                passer = next((p for p in events if p["id"] == kp), None)
                if passer:
                    assist_for[ev["id"]] = passer["player"]["id"]

    # Goals
    goal_evs = [ev for ev in events if is_goal(ev)]
    score_by_team = defaultdict(int)
    goals_by_period_team = defaultdict(lambda: defaultdict(int))
    running_score = []
    for ev in goal_evs:
        tid = ev["team"]["id"]
        score_by_team[tid] += 1
        goals_by_period_team[ev["period"]][tid] += 1
        running_score.append({
            "time":        match_clock(ev),
            "player_id":   str(ev["player"]["id"]),
            "assist_id":   str(assist_for.get(ev["id"])) if assist_for.get(ev["id"]) else None,
            "team_id":     str(tid),
            "is_own_goal": ev["shot"]["outcome"]["name"] == "Own Goal",
            "is_penalty":  ev["shot"]["type"]["name"]    == "Penalty",
            "score": {
                "home": score_by_team[home_id],
                "away": score_by_team[away_id],
            },
        })

    def score(side, sb_period):
        tid = home_id if side == "home" else away_id
        return goals_by_period_team[sb_period].get(tid, 0)

    sheet = {
        "match_id": match_id,
        "match": {
            "status": {
                "is_neutral": False,
                "has_extratime": any(ev["period"] in (3, 4) for ev in events),
                "has_shootout":  any(ev["period"] == 5      for ev in events),
            },
            "result": {
                "final": {
                    "home": score_by_team[home_id],
                    "away": score_by_team[away_id],
                    "winning_team_id": (
                        str(home_id if score_by_team[home_id] > score_by_team[away_id] else away_id)
                        if score_by_team[home_id] != score_by_team[away_id] else None
                    )
                },
                "first_half": {
                    "home": score("home", 1),
                    "away": score("away", 1),
                },
                "second_half": {
                    "home": score("home", 2),
                    "away": score("away", 2),
                },
                "first_half_extratime": {
                    "home": score("home", 3),
                    "away": score("away", 3),
                },
                "second_half_extratime": {
                    "home": score("home", 4),
                    "away": score("away", 4),
                },
                "shootout": {
                    "home": score("home", 5),
                    "away": score("away", 5),
                },
            },
        },
        "teams": {},
        "referees": [],
        "events": {
            "goals":         running_score,
            "substitutions": [],
            "cards":         [],
        },
        "meta": {"vendor": "StatsBomb"},
    }

    # Referees (matches file)
    if matches_file:
        m = next((mm for mm in matches_file if str(mm["match_id"]) == str(match_id)), None)
        if m and m.get("referee"):
            r = m["referee"]
            sheet["referees"].append({"id": str(r.get("id")), "name": r.get("name")})

    # Players
    for idx, tid in enumerate((home_id, away_id)):
        side = "home" if idx == 0 else "away"
        sheet["teams"][side] = {"id": str(tid), "players": []}
        for p in ids[tid]["lineup"]:
            starter = any(pos["start_reason"] == "Starting XI" for pos in p["positions"])
            sheet["teams"][side]["players"].append({
                "id":            str(p["player_id"]),
                "first_name":    p["player_name"].split(" ")[0],
                "last_name":     " ".join(p["player_name"].split(" ")[1:]),
                "team_id":       str(tid),
                "jersey_number": p.get("jersey_number"),
                "is_starter":    starter,
                "has_played":    bool(p["positions"]),
            })

    # Substitutions
    for ev in events:
        if ev["type"]["name"] != "Substitution":
            continue
        sub = ev.get("substitution", {})
        if "replacement" not in sub:
            continue
        sheet["events"]["substitutions"].append({
            "in_time":       match_clock(ev),
            "in_player_id":  str(sub["replacement"]["id"]),
            "out_time":      match_clock(ev),
            "out_player_id": str(ev["player"]["id"]),
            "team_id":       str(ev["team"]["id"]),
        })

    # Cards (Card / Foul Committed / Bad Behaviour)
    for ev in events:
        card_obj = None
        tname = ev["type"]["name"]
        if tname == "Card":
            card_obj = ev.get("card")
        elif tname == "Foul Committed":
            card_obj = ev.get("foul_committed", {}).get("card")
        elif tname == "Bad Behaviour":
            card_obj = ev.get("bad_behaviour", {}).get("card")

        if not card_obj:
            continue

        raw_type = (
            card_obj.get("type", {}).get("name")
            if isinstance(card_obj.get("type"), dict)
            else card_obj.get("name")
        )
        card_type = (raw_type or "unknown").lower()

        sheet["events"]["cards"].append({
            "time":       match_clock(ev),
            "player_id":  str(ev.get("player", {}).get("id")),
            "type":       card_type,
            "team_id":    str(ev["team"]["id"]),
        })

    return sheet


def build_event_cdf(events, match_id):
    meta_events = {"starting xi", "half start", "half end"}
    keep_meta = False
    rows = []
    for ev in events:
        if not keep_meta and ev["type"]["name"].lower() in meta_events:
            continue

        outcome_obj = (ev.get("shot") or ev.get("pass") or ev.get("carry") or {}).get("outcome", {})
        outcome = outcome_obj.get("name")

        recv_time = None
        if "pass" in ev and "duration" in ev:
            start = datetime.strptime(match_clock(ev), "%H:%M:%S.%f")
            recv_time = (start + timedelta(seconds=ev["duration"])).strftime("%H:%M:%S.%f")[:-3]

        rows.append({
            "match_id":                match_id,
            "meta":                    {"is synced": False},
            "event_id":                ev["id"],
            "event_time":              match_clock(ev),
            "event_period":            period_name(ev["period"]),
            "event_type":              ev["type"]["name"].lower(),
            "event_sub_type":          (ev.get("shot", {}).get("type", {}).get("name")
                                         or ev.get("pass", {}).get("type", {}).get("name")),
            "event_is_successful":     outcome not in ("Incomplete", "Out", None),
            "event_outcome_type":      outcome,
            "event_player_id":         ev.get("player", {}).get("id"),
            "event_team_id":           ev["team"]["id"],
            "event_receiver_id":       ev.get("pass", {}).get("recipient", {}).get("id"),
            "event_receiver_time":     recv_time,
            "event_x":                 ev.get("location", [None, None])[0],
            "event_y":                 ev.get("location", [None, None])[1],
            "event_x_end":             (ev.get("pass", {}).get("end_location")
                                         or ev.get("carry", {}).get("end_location")
                                         or [None, None])[0],
            "event_y_end":             (ev.get("pass", {}).get("end_location")
                                         or ev.get("carry", {}).get("end_location")
                                         or [None, None])[1],
            "event_body_part":         ev.get("pass", {}).get("body_part", {}).get("name"),
            "event_related_event_ids": ev.get("related_events", []),
        })
    return rows


def build_match_meta(events, lineup, match_id, matches_file=None):
    # Defaults from lineup
    comp_id   = lineup[0].get("comp_id")
    season_id = lineup[0].get("season_id")

    home_id, away_id = lineup[0]["team_id"], lineup[1]["team_id"]

    kickoff_time = None
    stadium_id = stadium_name = pitch_len = pitch_wid = None
    referee = None

    match_rec = None
    if matches_file:
        match_rec = next((m for m in matches_file if str(m["match_id"]) == str(match_id)), None)
        if match_rec:
            # competition & season fallbacks
            if comp_id is None:
                comp_id = (match_rec.get("competition", {}) or {}).get("competition_id") \
                          or match_rec.get("competition_id")
            if season_id is None:
                season_id = (match_rec.get("season", {}) or {}).get("season_id") \
                            or match_rec.get("season_id")

            if not kickoff_time and match_rec.get("match_date") and match_rec.get("kick_off"):
                kickoff_time = f"{match_rec['match_date']}T{match_rec['kick_off']}Z"

            ref = match_rec.get("referee")
            if ref:
                referee = {"id": ref.get("id"), "name": ref.get("name")}

            stadium = match_rec.get("stadium")
            if stadium:
                stadium_id   = stadium.get("id")
                stadium_name = stadium.get("name")
            stadium_id = stadium_id or match_rec.get("stadium_id")
            pitch_len  = match_rec.get("pitch_length")
            pitch_wid  = match_rec.get("pitch_width")

    # play direction
    first5 = [e for e in events
              if e["period"] == 1
              and e.get("minute", 0) < 5
              and e["team"]["id"] == home_id
              and e.get("location")]
    xs = [e["location"][0] for e in first5]
    play_dir_1st = None
    if xs:
        play_dir_1st = "left right" if sum(xs) / len(xs) < 60 else "right left"
    play_dir_2nd = ("right left" if play_dir_1st == "left right" else "left right") if play_dir_1st else None

    # whistles
    whistles = []
    for ev in events:
        if ev["type"]["name"] in ("Half Start", "Half End"):
            whistles.append({
                "type": ev["type"]["name"].lower(),
                "sub_type": None,
                "time": match_clock(ev)
            })

    def player_obj(p, team_id):
        starter = any(pos["start_reason"] == "Starting XI" for pos in p["positions"])
        return {
            "id": str(p["player_id"]),
            "team_id": str(team_id),
            "jersey_number": p.get("jersey_number"),
            "is_starter": starter
        }

    teams_block = {
        "home": {
            "id": str(home_id),
            "players": [player_obj(p, home_id) for p in lineup[0]["lineup"]]
        },
        "away": {
            "id": str(away_id),
            "players": [player_obj(p, away_id) for p in lineup[1]["lineup"]]
        }
    }

    meta = {
        "competition_id": comp_id,
        "season_id": season_id,
        "match_id": match_id,
        "match_kickoff_time": kickoff_time,
        "match": {
            "periods": [
                {"type": "first half",  "play_direction": play_dir_1st},
                {"type": "second half", "play_direction": play_dir_2nd},
            ],
            "whistles": whistles
        },
        "teams": teams_block,
        "stadium_id": stadium_id,
        "stadium": {
            "name": stadium_name,
            "pitch_length": pitch_len,
            "pitch_width":  pitch_wid
        },
        "meta": {
            "video_perspective": None,
            "event_version": "1.0",
            "event_name":    "StatsBomb",
            "meta_version":  "1.0",
            "meta_name":     "StatsBomb",
            "cdf_version":   "1.0"
        }
    }
    if referee:
        meta["referee"] = referee

    return meta

def run_single(events_path, lineup_path, matches_path, out_dir, match_id):
    events  = load(events_path)
    lineup  = load(lineup_path)
    matches = load(matches_path) if matches_path else None

    
    if not match_id:
        m = re.search(r"(\d{5,})", os.path.basename(events_path))
        match_id = m.group(1) if m else "unknown_match"

    target = Path(out_dir) / str(match_id)

    dump(build_match_sheet(events, lineup, match_id, matches_file=matches),
         target / "match_sheet_cdf.json")
    dump(build_event_cdf(events, match_id),
         target / "event_cdf.json")
    dump(build_match_meta(events, lineup, match_id,
                          matches_file=matches),
         target / "match_meta_cdf.json")


def run_batch(root, comp_ids, season_ids, out_dir):
    root = Path(root)
    for comp in comp_ids:
        for season in season_ids:
            matches_file = root / "data" / "matches" / str(comp) / f"{season}.json"
            if not matches_file.exists():
                print(f"No matches file: {matches_file}")
                continue
            matches = load(matches_file)
            for m in matches:
                mid = str(m["match_id"])
                ev_p = root / "data" / "events"  / f"{mid}.json"
                li_p = root / "data" / "lineups" / f"{mid}.json"
                if not ev_p.exists() or not li_p.exists():
                    print(f"Missing events/lineups for match {mid}")
                    continue
                run_single(ev_p, li_p, matches_file, out_dir,
                           match_id=mid)


def main():
    ap = argparse.ArgumentParser(description="StatsBomb → Football CDF")
    # single mode
    ap.add_argument("--events")
    ap.add_argument("--lineup")
    ap.add_argument("--matches")
    ap.add_argument("--out-dir", default="cdf_out")
    # batch mode
    ap.add_argument("--root", help="Root of statsbomb open-data (has /data/…)")
    ap.add_argument("--competitions", nargs="+", help="Competition ids for batch")
    ap.add_argument("--seasons",      nargs="+", help="Season ids for batch")
    args = ap.parse_args()

    if args.root:
        if not (args.competitions and args.seasons):
            ap.error("Batch mode needs --competitions and --seasons")
        run_batch(args.root,
                  [int(c) for c in args.competitions],
                  [int(s) for s in args.seasons],
                  args.out_dir)
    else:
        if not (args.events and args.lineup):
            ap.error("Single mode needs --events and --lineup")
        run_single(args.events, args.lineup, args.matches, args.out_dir, None)
    return 0

if __name__ == "__main__":
    sys.exit(main())
