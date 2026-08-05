import re
from pathlib import Path

from .grammar import EVENT_WORDS, check, load_nodetypes

OWNER_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


def run_checks(conn, board, grammar, stale_hours=24.0):
    board = Path(board)
    ok, issues = [], []

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    (ok if integrity == "ok" else issues).append(f"db integrity: {integrity}")

    if grammar is None:
        issues.append("no transitions.yaml found")
    else:
        findings = check(grammar, load_nodetypes(board / "nodetypes.yaml"))
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
        "SELECT p.id FROM nodes p JOIN nodes c ON c.parent=p.id "
        "WHERE p.state='blocked' AND c.state='rejected'").fetchall()
    if orphaned:
        issues.append("blocked parent with rejected child (decide manually): "
                      + ", ".join(r["id"] for r in orphaned))

    counts = {s: conn.execute(
        "SELECT COUNT(*) c FROM nodes WHERE state=?", (s,)).fetchone()["c"]
        for s in ("proposed", "pending", "active", "blocked", "done")}
    if not any(counts[s] for s in ("proposed", "pending", "active", "blocked")):
        ok.append(f"chain at rest ({counts['done']} done) - harvest results "
                  f"or seed the next round")

    return ok, issues


def render_report(ok, issues):
    lines = [f"ok: {l}" for l in ok] + [f"issue: {l}" for l in issues]
    lines.append(f"doctor: {len(issues)} issue(s)" if issues else "doctor: healthy")
    return "\n".join(lines)
