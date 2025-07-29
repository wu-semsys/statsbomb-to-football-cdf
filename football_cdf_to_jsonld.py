import argparse
import json
import numbers
import urllib.parse as url
from pathlib import Path

from rdflib import Graph, Namespace, Literal
from rdflib.namespace import RDF, XSD, OWL

CORE = Namespace("https://w3id.org/football-cdf/core#")
def core(local: str): return CORE[local]

def slug(text: str) -> str:
    return url.quote(str(text).lower().replace(" ", "_"), safe="_")

def lit(v, dt=None):
    if v is None:
        return None
    if dt:
        return Literal(v, datatype=dt)
    if isinstance(v, bool):
        return Literal(v, datatype=XSD.boolean)
    if isinstance(v, numbers.Integral):
        return Literal(int(v), datatype=XSD.integer)
    if isinstance(v, numbers.Real):
        return Literal(float(v), datatype=XSD.float)
    if isinstance(v, str) and v.endswith("Z") and "T" in v:
        return Literal(v, datatype=XSD.dateTime)
    return Literal(v, datatype=XSD.string)

def add(g: Graph, s, p, v, dt=None):
    if v is not None:
        g.add((s, p, lit(v, dt)))
        
def build_graph(sheet_fp, events_fp, meta_fp) -> Graph:
    sheet  = json.load(open(sheet_fp,  encoding="utf-8"))
    events = json.load(open(events_fp, encoding="utf-8"))
    meta   = json.load(open(meta_fp,   encoding="utf-8"))

    g = Graph()
    g.bind("", CORE); g.bind("xsd", XSD); g.bind("owl", OWL)

    mid   = str(meta["match_id"])
    m_uri = core(f"match/{mid}")
    g.add((m_uri, RDF.type, core("Match"))); add(g, m_uri, core("id"), mid)

    # competition / season
    for tag in ("competition", "season"):
        cid = meta.get(f"{tag}_id") or meta.get(f"{tag} id")
        if cid is not None:
            uri = core(f"{tag}/{cid}")
            g.add((uri, RDF.type, core(tag.capitalize())))
            add(g, uri, core("id"), cid)
            g.add((m_uri, core(tag), uri))

    # kickoff
    add(g, m_uri, core("kickoff_time"),
        meta.get("match_kickoff_time") or meta.get("match kickoff time"))

    # Match_Status
    status = sheet["match"]["status"]
    st_uri = core(f"match_status/{mid}")
    g.add((st_uri, RDF.type, core("Match_Status")))
    g.add((m_uri, core("match_status"), st_uri))
    for src_key in ("is_neutral", "has_extratime", "has_shootout"):
        val = status.get(src_key) or status.get(src_key.replace("_", " "))
        add(g, st_uri, core(src_key), val)

    # Match_Result
    for period, val in sheet["match"]["result"].items():
        if period == "final winning team id":
            continue
        r_uri = core(f"match_result/{mid}/{slug(period)}")
        g.add((r_uri, RDF.type, core("Match_Result")))
        g.add((m_uri, core("match_result"), r_uri))
        add(g, r_uri, core("result_period"), period)
        add(g, r_uri, core("result_home"), val.get("home"), XSD.integer)
        add(g, r_uri, core("result_away"), val.get("away"), XSD.integer)

    # stadium & referee
    stadium = meta.get("stadium") or {}
    sid = (meta.get("stadium_id") or meta.get("stadium id") or
           stadium.get("id"))
    if sid:
        s_uri = core(f"stadium/{sid}")
        g.add((s_uri, RDF.type, core("Stadium")))
        add(g, s_uri, core("id"), sid)
        add(g, s_uri, core("name"), stadium.get("name"))
        add(g, s_uri, core("pitch_length"),
            stadium.get("pitch_length") or stadium.get("pitch length"), XSD.float)
        add(g, s_uri, core("pitch_width"),
            stadium.get("pitch_width")  or stadium.get("pitch width"),  XSD.float)
        g.add((m_uri, core("stadium_id"), s_uri))

    if "referee" in meta and meta["referee"]:
        ref = meta["referee"]
        r_uri = core(f"referee/{ref.get('id','unknown')}")
        g.add((r_uri, RDF.type, core("Referee")))
        add(g, r_uri, core("id"),   ref.get("id"))
        add(g, r_uri, core("name"), ref.get("name"))
        g.add((m_uri, core("referee"), r_uri))

    # teams & players
    id2player = {}
    for side in ("home", "away"):
        t = sheet["teams"][side]
        t_uri = core(f"team/{t['id']}")
        g.add((t_uri, RDF.type, core("Team"))); add(g, t_uri, core("id"), t["id"])
        g.add((m_uri, core(f"teams_{side}"), t_uri))

        for p in t["players"]:
            p_uri = core(f"player/{p['id']}")
            id2player[str(p["id"])] = p_uri
            g.add((p_uri, RDF.type, core("Player")))
            g.add((t_uri, core("players"), p_uri))

            first = p.get("first_name")
            last  = p.get("last_name")
            pname = p.get("player_name") or " ".join(x for x in [first, last] if x)

            add(g, p_uri, core("id"),            p["id"])
            add(g, p_uri, core("first_name"),    first)
            add(g, p_uri, core("last_name"),     last)
            add(g, p_uri, core("player_name"),   pname)         
            add(g, p_uri, core("jersey_number"), p.get("jersey_number"), XSD.integer)
            add(g, p_uri, core("is_starter"),    p.get("is_starter"))
            add(g, p_uri, core("has_played"),    p.get("has_played"))
            g.add((p_uri, core("team_id"), t_uri))

    # whistles
    for w in meta["match"]["whistles"]:
        w_uri = core(f"whistle/{mid}/{slug(w['time'])}")
        g.add((w_uri, RDF.type, core("Whistle")))
        g.add((m_uri, core("match/whistles"), w_uri))
        add(g, w_uri, core("type"), w["type"])
        add(g, w_uri, core("sub_type"), w.get("sub_type"))
        add(g, w_uri, core("time"), w["time"])

    # periods w/ play_direction
    for pr in meta["match"]["periods"]:
        if pr.get("play_direction"):
            p_uri = core(f"period/{mid}/{slug(pr['type'])}")
            g.add((p_uri, RDF.type, core("Period")))
            g.add((m_uri, core("match/periods"), p_uri))
            add(g, p_uri, core("type"), pr["type"])
            add(g, p_uri, core("play_direction"), pr["play_direction"])

    # lookups from sheet
    goal_lkp = {(g0["time"], str(g0["player_id"]), str(g0["team_id"])): g0
                for g0 in sheet["events"]["goals"]}
    sub_lkp  = {s["in_time"]: s for s in sheet["events"]["substitutions"]}
    card_lkp = {(c["time"], str(c["player_id"])): c
                for c in sheet["events"]["cards"]}

    # events
    for ev in events:
        e_uri = core(f"event/{ev['event_id']}")
        g.add((e_uri, RDF.type, core("Event")))
        g.add((m_uri, core("events"), e_uri))

        for pred, val, dt in [
            ("id",           ev["event_id"], None),
            ("time",         ev["event_time"], None),
            ("event_period", ev["event_period"].replace(" ", "_"), None),
            ("type",         ev["event_type"], None),
            ("sub_type",     ev["event_sub_type"], None),
            ("outcome_type", ev["event_outcome_type"], None),
            ("x",            ev["event_x"], XSD.float),
            ("y",            ev["event_y"], XSD.float),
            ("x_end",        ev["event_x_end"], XSD.float),
            ("y_end",        ev["event_y_end"], XSD.float),
            ("body_part",    ev["event_body_part"], None),
        ]:
            add(g, e_uri, core(pred), val, dt)

        # links
        if ev["event_player_id"]:
            g.add((e_uri, core("player_id"), id2player[str(ev["event_player_id"])]))
        g.add((e_uri, core("team_id"), core(f"team/{ev['event_team_id']}")))

        etype   = ev["event_type"]
        outcome = (ev["event_outcome_type"] or "").lower()

        # Shot / Goal
        if etype == "shot":
            g.add((e_uri, RDF.type, core("Shot")))
            if outcome in {"goal", "successful"}:
                g.add((e_uri, RDF.type, core("Goal")))
                key = (ev["event_time"], str(ev["event_player_id"]), str(ev["event_team_id"]))
                gd = goal_lkp.get(key)
                if gd:
                    if gd["assist_id"]:
                        g.add((e_uri, core("assist_id"), id2player[str(gd["assist_id"])]))
                    add(g, e_uri, core("is_own_goal"), gd["is_own_goal"])
                    add(g, e_uri, core("is_penalty"),  gd["is_penalty"])

        # Pass
        if etype == "pass":
            g.add((e_uri, RDF.type, core("Pass")))
            rid = ev.get("event_receiver_id")
            if rid:
                recv = id2player.get(str(rid), core(f"player/{rid}"))
                g.add((e_uri, core("receiver_id"), recv))
            add(g, e_uri, core("receiver_time"), ev.get("event_receiver_time"))

        # Substitution
        if etype == "substitution":
            g.add((e_uri, RDF.type, core("Subtitution")))
            sd = sub_lkp.get(ev["event_time"])
            if sd:
                g.add((e_uri, core("out_player_id"), id2player[str(sd["out_player_id"])]))
                add(g, e_uri, core("out_time"), sd["out_time"])

        # Card
        ck = (ev["event_time"], str(ev.get("event_player_id") or ""))
        cinfo = card_lkp.get(ck)
        if etype == "card" or cinfo:
            g.add((e_uri, RDF.type, core("Card")))
            ctype = (cinfo or {}).get("type")
            add(g, e_uri, core("card_type"), ctype)

    # meta node
    meta_uri = core(f"meta/{mid}")
    g.add((meta_uri, RDF.type, core("Meta")))
    add(g, meta_uri, core("version"), "0.1.0")
    add(g, meta_uri, core("vendor"),  "StatsBomb")
    g.add((m_uri, core("meta_meta"), meta_uri))
    g.add((m_uri, core("meta_video"), meta_uri))
    g.add((m_uri, core("meta_landmarks"), meta_uri))

    return g

def convert_one(match_dir: Path, out_dir: Path):
    sheet  = match_dir / "match_sheet_cdf.json"
    events = match_dir / "event_cdf.json"
    meta   = match_dir / "match_meta_cdf.json"
    if not (sheet.exists() and events.exists() and meta.exists()):
        print(f"Missing CDF files in {match_dir}")
        return
    g = build_graph(sheet, events, meta)
    context = {"@vocab": str(CORE), "xsd": str(XSD)}
    out_path = out_dir / f"{match_dir.name}.jsonld"
    out_dir.mkdir(parents=True, exist_ok=True)
    g.serialize(out_path, format="json-ld", context=context, indent=2)
    print(f"JSON‑LD written → {out_path}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    # single
    ap.add_argument("--sheet")
    ap.add_argument("--events")
    ap.add_argument("--meta")
    ap.add_argument("--out", default="out/match.jsonld")
    # batch
    ap.add_argument("--root", help="Dir containing per-match CDF folders")
    ap.add_argument("--out-dir", help="Output dir for batch JSON-LD")
    args = ap.parse_args()

    if args.root:
        if not args.out_dir:
            ap.error("Batch mode requires --out-dir")
        root = Path(args.root)
        for match_dir in root.iterdir():
            if match_dir.is_dir():
                convert_one(match_dir, Path(args.out_dir))
    else:
        if not (args.sheet and args.events and args.meta):
            ap.error("Single mode needs --sheet --events --meta")
        g = build_graph(args.sheet, args.events, args.meta)
        context = {"@vocab": str(CORE), "xsd": str(XSD)}
        out_f = Path(args.out); out_f.parent.mkdir(parents=True, exist_ok=True)
        g.serialize(out_f, format="json-ld", context=context, indent=2)
        print("JSON‑LD written →", out_f)
