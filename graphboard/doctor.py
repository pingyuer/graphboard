import re
from pathlib import Path

from .db import OPEN_STATES
from .grammar import EVENT_WORDS, check, load_nodetypes

OWNER_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def run_checks(conn, board, grammar, stale_hours=24.0, orphan_hours=4.0):
    board = Path(board)
    ok, issues = [], []

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    (ok if integrity == "ok" else issues).append(f"db integrity: {integrity}")

    if grammar is None:
        issues.append("no transitions.yaml found")
    else:
        nodetypes = load_nodetypes(board / "nodetypes.yaml")
        findings = check(grammar, nodetypes)
        errors = [m for lvl, m in findings if lvl == "error"]
        if errors:
            issues.extend(f"grammar error: {m}" for m in errors)
        else:
            ok.append(f"grammar OK ({len(grammar.rules)} rules)")
        for r in grammar.rules:
            if r.frm in EVENT_WORDS:
                issues.append(f"grammar rule looks swapped: {r.frm} --{r.on}--> "
                              f"{r.to} (from_type should be a node type, not an "
                              f"event); fix with grammar remove/add")

    nodetypes = load_nodetypes(board / "nodetypes.yaml")
    placeholders = [t for t, spec in nodetypes.items()
                    if isinstance(spec, dict) and
                    str(spec.get("contract", "")).startswith("TODO")]
    if placeholders:
        issues.append("placeholder contract(s) not filled in: "
                      + ", ".join(placeholders)
                      + " - edit nodetypes.yaml")

    owned = conn.execute(
        "SELECT id, owner FROM nodes WHERE owner IS NOT NULL AND owner != ''"
    ).fetchall()
    bad = [r["id"] for r in owned if not OWNER_RE.match(r["owner"])]
    if bad:
        issues.append(f"owner not in role-instance format: {', '.join(bad)}")
    else:
        ok.append(f"owner format OK ({len(owned)} owned nodes)")

    active = conn.execute(
        "SELECT id FROM nodes WHERE state='active'").fetchall()
    missing_wd = [r["id"] for r in active
                  if not (board / "nodes" / r["id"] / "out").is_dir()]
    if missing_wd:
        issues.append(f"active node missing workdir: {', '.join(missing_wd)}")
    else:
        ok.append(f"workdirs OK ({len(active)} active nodes)")

    stale = conn.execute(
        "SELECT id, type FROM nodes WHERE state='proposed' AND "
        "created_at < strftime('%Y-%m-%dT%H:%M:%S','now',?)",
        (f"-{float(stale_hours)} hours",)).fetchall()
    if stale:
        issues.append(f"stale proposed (> {stale_hours}h): "
                      + ", ".join(f"{r['id']} ({r['type']})" for r in stale))
    else:
        ok.append("no stale proposed nodes")

    phantom = conn.execute(
        "SELECT id FROM nodes WHERE state='pending' AND "
        "(note LIKE '%claim%' OR note LIKE '%Claim%')").fetchall()
    if phantom:
        issues.append("pending node with claim-like note (claimed without pull): "
                      + ", ".join(r["id"] for r in phantom)
                      + " - owner must pull to claim properly")
    else:
        ok.append("no phantom claims")

    orphaned = conn.execute(
        "SELECT id, owner FROM nodes WHERE state='active' AND "
        "updated_at < strftime('%Y-%m-%dT%H:%M:%S','now',?)",
        (f"-{float(orphan_hours)} hours",)).fetchall()
    if orphaned:
        issues.append("possibly orphaned active node(s), no update for >"
                      f"{orphan_hours}h: "
                      + ", ".join(f"{r['id']} [{r['owner'] or '-'}]"
                                  for r in orphaned)
                      + " - verify the owner session is alive; if dead, "
                        "release the node so a new worker can re-pull it")
    else:
        ok.append("no orphaned active nodes")

    orphaned_parents = conn.execute(
        "SELECT p.id FROM nodes p JOIN nodes c ON c.parent=p.id "
        "WHERE p.state='blocked' AND c.state='rejected'").fetchall()
    if orphaned_parents:
        issues.append("blocked parent with rejected child (decide manually): "
                      + ", ".join(r["id"] for r in orphaned_parents))

    due_running = conn.execute(
        "SELECT id, owner, resources FROM nodes WHERE state='running' AND "
        "check_after IS NOT NULL AND "
        "check_after < strftime('%Y-%m-%dT%H:%M:%S','now')").fetchall()
    if due_running:
        issues.append("running node(s) due for check (check_after passed): "
                      + ", ".join(f"{r['id']} [{r['owner'] or '-'}] "
                                  f"({r['resources'] or 'no resources'})"
                                  for r in due_running)
                      + " - harvest or extend via reactivate/note")
    else:
        ok.append("no running nodes due for check")

    multi = conn.execute(
        "SELECT owner, COUNT(*) c FROM nodes WHERE state='active' "
        "AND owner IS NOT NULL AND owner != '' GROUP BY owner HAVING c > 1"
    ).fetchall()
    if multi:
        issues.append("owner(s) holding multiple active nodes (attention is "
                      "one-at-a-time; delegate long-running work to running "
                      "instead): " + ", ".join(f"{r['owner']} x{r['c']}"
                                               for r in multi))
    else:
        ok.append("attention OK (no owner holds multiple active nodes)")

    expired_ann = conn.execute(
        "SELECT COUNT(*) c FROM announcements WHERE active=1 AND "
        "expires_at IS NOT NULL AND "
        "expires_at < strftime('%Y-%m-%dT%H:%M:%S','now')").fetchone()["c"]
    if expired_ann:
        issues.append(f"{expired_ann} expired announcement(s) still active - "
                      f"clear with announce --clear")

    fact_chars = conn.execute(
        "SELECT COALESCE(SUM(LENGTH(key) + LENGTH(value)), 0) c FROM facts"
    ).fetchone()["c"]
    if fact_chars > 1200:
        issues.append(f"facts store is large ({fact_chars} chars) - facts are for "
                      f"a few volatile truths (ports/URIs); move stable context into "
                      f"init artifacts or the repo")

    archivable = conn.execute(
        "SELECT COUNT(*) c FROM nodes WHERE archived=0 AND state IN "
        "('done','rejected','canceled') AND "
        "updated_at < strftime('%Y-%m-%dT%H:%M:%S','now','-14 days')").fetchone()["c"]
    if archivable:
        ok.append(f"{archivable} terminal node(s) older than 14 days - "
                  f"consider 'gb archive' to tidy live views")

    counts = {s: conn.execute(
        "SELECT COUNT(*) c FROM nodes WHERE state=? AND archived=0", (s,)
    ).fetchone()["c"] for s in OPEN_STATES + ("proposed", "done")}
    if not any(counts[s] for s in OPEN_STATES + ("proposed",)):
        ok.append(f"chain at rest ({counts['done']} done) - harvest results "
                  f"or seed the next round")

    return ok, issues


def render_report(ok, issues):
    lines = [f"ok: {l}" for l in ok] + [f"issue: {l}" for l in issues]
    lines.append(f"doctor: {len(issues)} issue(s)" if issues else "doctor: healthy")
    return "\n".join(lines)
