import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import grammar as grammar_mod
from .db import OPEN_STATES, STATES, TERMINAL_STATES


class GbError(Exception):
    pass


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_id(conn):
    for _ in range(5):
        ts = datetime.now(timezone.utc)
        nid = f"n-{ts:%Y%m%d}-{ts:%H%M%S}-{secrets.token_hex(2)[:3]}"
        if conn.execute("SELECT 1 FROM nodes WHERE id=?", (nid,)).fetchone() is None:
            return nid
    raise GbError("failed to allocate unique node id")


def parse_outputs(spec):
    if isinstance(spec, str):
        parts = [p for p in spec.split(";") if p.strip()]
    else:
        parts = spec or ()
    outputs = []
    for part in parts:
        path, _, note = str(part).partition(":")
        if not path.strip():
            raise GbError(f"output entry must be PATH[:NOTE], got {part!r}")
        outputs.append({"path": path.strip(), "note": note.strip() or None})
    return outputs


def parse_successors(spec):
    if isinstance(spec, str):
        parts = [p for p in spec.split(";") if p.strip()]
    else:
        parts = spec or ()
    succs = []
    for part in parts:
        stype, sep, sspec = str(part).partition("|")
        if not sep or not sspec.strip():
            raise GbError(f"successor/child entry must be TYPE|SPEC, got {part!r}")
        succs.append({"type": stype.strip(), "spec": sspec.strip()})
    return succs


def _node(conn, node_id):
    row = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
    if row is None:
        raise GbError(f"node not found: {node_id}")
    return row


def _board_dir(conn):
    for row in conn.execute("PRAGMA database_list").fetchall():
        if row["name"] == "main" and row["file"]:
            return Path(row["file"]).parent
    raise GbError("cannot resolve board directory from connection")


def _event(conn, tool, owner, node_id, detail=""):
    conn.execute(
        "INSERT INTO events(ts, tool, owner, node_id, detail) VALUES(?,?,?,?,?)",
        (now_iso(), tool, owner or "", node_id or "", str(detail or "")[:200]))


def _fail(conn, tool, owner, node_id, msg):
    _event(conn, tool, owner, node_id, f"error: {msg}")
    conn.commit()
    raise GbError(msg)


def _unread_announcements(conn, owner):
    rows = conn.execute(
        "SELECT id, text FROM announcements WHERE active=1 "
        "AND (expires_at IS NULL OR expires_at > ?) AND id NOT IN "
        "(SELECT ann_id FROM announcement_reads WHERE owner=?) ORDER BY id",
        (now_iso(), owner)).fetchall()
    for r in rows:
        conn.execute(
            "INSERT OR IGNORE INTO announcement_reads(owner, ann_id) VALUES(?,?)",
            (owner, r["id"]))
    return [dict(r) for r in rows]


def pull(conn, owner, type_filter=None, contracts=None):
    q = "SELECT * FROM nodes WHERE state='pending'"
    args = []
    if type_filter:
        q += " AND type=?"
        args.append(type_filter)
    q += " ORDER BY created_at ASC, rowid ASC LIMIT 5"
    candidates = conn.execute(q, args).fetchall()
    ts = now_iso()
    for row in candidates:
        cur = conn.execute(
            "UPDATE nodes SET state='active', owner=?, updated_at=? "
            "WHERE id=? AND state='pending'", (owner, ts, row["id"]))
        if cur.rowcount == 1:
            conn.commit()
            node = _node(conn, row["id"])
            workdir = _board_dir(conn) / "nodes" / node["id"] / "out"
            workdir.mkdir(parents=True, exist_ok=True)
            inputs = []
            if node["parent"]:
                inputs = [
                    {"path": o["path"], "note": o["note"], "from": node["parent"]}
                    for o in conn.execute(
                        "SELECT path, note FROM outputs WHERE node_id=? "
                        "ORDER BY created_at", (node["parent"],)).fetchall()]
            announcements = _unread_announcements(conn, owner)
            _event(conn, "pull", owner, node["id"])
            conn.commit()
            contract = (contracts or {}).get(node["type"])
            if isinstance(contract, dict):
                contract = contract.get("contract")
            return {
                "claimed": {
                    "id": node["id"], "type": node["type"], "spec": node["spec"],
                    "note": node["note"], "parent": node["parent"],
                    "on_event": node["on_event"],
                    "workdir": str(workdir),
                },
                "inputs": inputs,
                "contract": contract,
                "announcements": announcements,
            }
    counts = {s: conn.execute(
        "SELECT COUNT(*) c FROM nodes WHERE state=?", (s,)).fetchone()["c"]
        for s in ("proposed",) + OPEN_STATES}
    awaiting = None
    if counts["proposed"]:
        q = "SELECT COUNT(*) c FROM nodes WHERE state='proposed'"
        args = []
        if type_filter:
            q += " AND type=?"
            args.append(type_filter)
        awaiting = conn.execute(q, args).fetchone()["c"]
    announcements = _unread_announcements(conn, owner)
    conn.commit()
    return {"claimed": None, "counts": counts, "awaiting_approval": awaiting,
            "announcements": announcements}


def _descendants(conn, root_id):
    _node(conn, root_id)
    seen = {root_id}
    frontier = [root_id]
    while frontier:
        placeholders = ",".join("?" * len(frontier))
        rows = conn.execute(
            f"SELECT id FROM nodes WHERE parent IN ({placeholders})",
            frontier).fetchall()
        frontier = [r["id"] for r in rows if r["id"] not in seen]
        seen.update(frontier)
    return seen


def query(conn, type=None, state=None, under=None, owner=None, limit=20):
    clauses, args = [], []
    if type:
        clauses.append("type=?")
        args.append(type)
    if state:
        clauses.append("state=?")
        args.append(state)
    if owner:
        clauses.append("owner=?")
        args.append(owner)
    if under:
        desc = _descendants(conn, under)
        clauses.append(f"id IN ({','.join('?' * len(desc))})")
        args.extend(sorted(desc))
    q = "SELECT * FROM nodes"
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY created_at ASC, rowid ASC LIMIT ?"
    args.append(max(1, int(limit)))
    nodes = []
    for row in conn.execute(q, args).fetchall():
        outputs = [{"path": o["path"], "note": o["note"]} for o in conn.execute(
            "SELECT path, note FROM outputs WHERE node_id=? ORDER BY created_at",
            (row["id"],)).fetchall()]
        nodes.append({"id": row["id"], "type": row["type"], "state": row["state"],
                      "owner": row["owner"], "spec": row["spec"],
                      "parent": row["parent"], "outputs": outputs,
                      "resources": row["resources"],
                      "check_after": row["check_after"]})
    return {"nodes": nodes, "truncated": len(nodes) >= int(limit)}


def _ancestor_type_count(conn, start_id, target_type):
    count = 0
    cur = start_id
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        row = conn.execute(
            "SELECT type, parent FROM nodes WHERE id=?", (cur,)).fetchone()
        if row is None:
            break
        if row["type"] == target_type:
            count += 1
        cur = row["parent"]
    return count


def _node_or_fail(conn, tool, owner, node_id):
    row = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
    if row is None:
        _fail(conn, tool, owner, node_id, f"node not found: {node_id}")
    return row


def _evaluate_successor(conn, grammar, node, ev, stype):
    if grammar is not None:
        activate, rule = grammar_mod.evaluate(grammar, node["type"], ev, stype)
    else:
        activate, rule = "approve", None
    state = "pending" if activate == "auto" else "proposed"
    reason = (f"grammar {activate}" if rule is not None
              else f"default {activate}")
    if rule is None and grammar is not None and grammar.rules:
        related = any(r.frm in (node["type"], "any") or
                      r.to in (stype, "any") for r in grammar.rules)
        if related:
            reason += " (no rule matched - check grammar)"
    if state == "pending" and rule is not None and rule.budget:
        if _ancestor_type_count(conn, node["id"], stype) >= rule.budget:
            state, reason = "proposed", "budget-exceeded"
    return state, reason


def _maybe_reactivate_parent(conn, node, ts):
    if not node["parent"]:
        return None
    parent = conn.execute("SELECT id, state FROM nodes WHERE id=?",
                          (node["parent"],)).fetchone()
    if parent is None or parent["state"] != "blocked":
        return None
    siblings = conn.execute(
        "SELECT state, on_event FROM nodes WHERE parent=?",
        (parent["id"],)).fetchall()
    if not siblings or any(s["on_event"] != "split" for s in siblings):
        return None
    if all(s["state"] == "done" for s in siblings):
        conn.execute(
            "UPDATE nodes SET state='pending', note=?, updated_at=? WHERE id=?",
            ("children complete, ready to integrate", ts, parent["id"]))
        _event(conn, "reactivate", "", parent["id"], "all split children done")
        return parent["id"]
    return None


def _undeclared_auto_notices(grammar, node, ev, successors):
    if grammar is None or not grammar.rules:
        return []
    declared = {s["type"] for s in successors}
    notices = []
    for r in grammar.rules:
        if r.activate != "auto" or r.on != ev or r.to == "any":
            continue
        if r.frm not in (node["type"], "any") or r.to in declared:
            continue
        notices.append(f"grammar defines {node['type']} --{ev}--> {r.to} (auto) "
                       f"but no such successor was declared")
    return notices


def submit(conn, node_id, owner, status, outputs=(), successors=(),
           event=None, note=None, grammar=None):
    node = _node_or_fail(conn, "submit", owner, node_id)
    if node["state"] not in ("active", "running"):
        msg = f"node {node_id} is {node['state']}, not active|running"
        if node["state"] == "done":
            msg += (f"; to attach successors after done, use propose with "
                    f"parent={node_id}")
        _fail(conn, "submit", owner, node_id, msg)
    if node["owner"] and node["owner"] != owner:
        _fail(conn, "submit", owner, node_id,
              f"node {node_id} is owned by {node['owner']}, not {owner}")
    if status not in ("done", "blocked"):
        _fail(conn, "submit", owner, node_id,
              f"status must be done|blocked, got {status!r}")
    if status == "done" and not outputs:
        _fail(conn, "submit", owner, node_id,
              "submit done requires at least one output; "
              "use status=blocked if the node cannot finish")
    ev = event or status
    ts = now_iso()

    for o in outputs:
        conn.execute(
            "INSERT INTO outputs(node_id, path, note, created_at) VALUES(?,?,?,?)",
            (node_id, o["path"], o.get("note"), ts))
    conn.execute(
        "UPDATE nodes SET state=?, note=?, resources=NULL, check_after=NULL, "
        "updated_at=? WHERE id=?",
        (status, note if note is not None else node["note"], ts, node_id))

    reactivated = _maybe_reactivate_parent(conn, node, ts)

    verdicts = []
    for succ in successors:
        stype, sspec = succ["type"], succ["spec"]
        state, reason = _evaluate_successor(conn, grammar, node, ev, stype)
        child_id = new_id(conn)
        conn.execute(
            "INSERT INTO nodes(id, type, state, parent, on_event, owner, spec, "
            "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (child_id, stype, state, node_id, ev, None, sspec, ts, ts))
        conn.execute(
            "INSERT INTO edges(from_id, on_event, to_id) VALUES(?,?,?)",
            (node_id, ev, child_id))
        verdicts.append({"id": child_id, "type": stype, "state": state,
                         "reason": reason})
    notices = _undeclared_auto_notices(grammar, node, ev, successors)
    _event(conn, "submit", owner, node_id,
           f"status={status} event={ev} outputs={len(outputs)} "
           f"successors={len(verdicts)}")
    conn.commit()
    return {"id": node_id, "state": status, "event": ev,
            "outputs": len(outputs), "successors": verdicts,
            "reactivated": reactivated, "notices": notices}


def split(conn, node_id, owner, children, grammar=None):
    node = _node_or_fail(conn, "split", owner, node_id)
    if node["state"] != "active":
        _fail(conn, "split", owner, node_id,
              f"node {node_id} is {node['state']}, only active nodes can split")
    if node["owner"] and node["owner"] != owner:
        _fail(conn, "split", owner, node_id,
              f"node {node_id} is owned by {node['owner']}, not {owner}")
    if not children:
        _fail(conn, "split", owner, node_id,
              "split requires at least one child (TYPE|SPEC)")
    ts = now_iso()
    verdicts = []
    for child in children:
        stype, sspec = child["type"], child["spec"]
        state, reason = _evaluate_successor(conn, grammar, node, "split", stype)
        child_id = new_id(conn)
        conn.execute(
            "INSERT INTO nodes(id, type, state, parent, on_event, owner, spec, "
            "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (child_id, stype, state, node_id, "split", None, sspec, ts, ts))
        conn.execute(
            "INSERT INTO edges(from_id, on_event, to_id) VALUES(?,?,?)",
            (node_id, "split", child_id))
        verdicts.append({"id": child_id, "type": stype, "state": state,
                         "reason": reason})
    conn.execute(
        "UPDATE nodes SET state='blocked', owner=NULL, note=?, updated_at=? "
        "WHERE id=?",
        (f"split into {len(verdicts)} children", ts, node_id))
    _event(conn, "split", owner, node_id, f"children={len(verdicts)}")
    conn.commit()
    return {"id": node_id, "state": "blocked", "children": verdicts}


def propose(conn, type, spec, parent=None, on=None):
    if parent is not None:
        _node_or_fail(conn, "propose", "", parent)
    ts = now_iso()
    nid = new_id(conn)
    conn.execute(
        "INSERT INTO nodes(id, type, state, parent, on_event, owner, spec, "
        "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (nid, type, "proposed", parent, on, None, spec, ts, ts))
    if parent is not None:
        conn.execute(
            "INSERT INTO edges(from_id, on_event, to_id) VALUES(?,?,?)",
            (parent, on or "proposed", nid))
    _event(conn, "propose", "", nid, f"type={type}")
    conn.commit()
    return nid


def status(conn, node_id=None):
    if node_id:
        node = _node(conn, node_id)
        parent = None
        if node["parent"]:
            p = conn.execute("SELECT id, type, state FROM nodes WHERE id=?",
                             (node["parent"],)).fetchone()
            parent = dict(p) if p else None
        children = [dict(r) for r in conn.execute(
            "SELECT id, type, state, on_event FROM nodes WHERE parent=? "
            "ORDER BY created_at, rowid", (node_id,)).fetchall()]
        outputs = [dict(r) for r in conn.execute(
            "SELECT path, note, created_at FROM outputs WHERE node_id=? "
            "ORDER BY created_at", (node_id,)).fetchall()]
        return {"node": dict(node), "parent": parent,
                "children": children, "outputs": outputs}
    counts = {}
    for s in STATES:
        counts[s] = conn.execute(
            "SELECT COUNT(*) c FROM nodes WHERE state=?", (s,)).fetchone()["c"]
    open_nodes = [dict(r) for r in conn.execute(
        "SELECT id, type, state, owner, spec, resources, check_after FROM nodes "
        "WHERE state IN ('pending','active','running','proposed','blocked') "
        "ORDER BY CASE state WHEN 'active' THEN 0 WHEN 'running' THEN 1 "
        "WHEN 'pending' THEN 2 WHEN 'blocked' THEN 3 ELSE 4 END, "
        "created_at, rowid").fetchall()]
    return {"counts": counts, "open": open_nodes}


def cancel(conn, node_id, reason=""):
    node = _node_or_fail(conn, "cancel", "", node_id)
    if node["state"] in TERMINAL_STATES:
        _fail(conn, "cancel", "", node_id,
              f"node {node_id} is already {node['state']}")
    conn.execute(
        "UPDATE nodes SET state='canceled', resources=NULL, check_after=NULL, "
        "updated_at=? WHERE id=?",
        (now_iso(), node_id))
    _event(conn, "cancel", "", node_id, reason or "canceled")
    conn.commit()


def hold(conn, node_id, reason=""):
    node = _node_or_fail(conn, "hold", "", node_id)
    if node["state"] not in ("proposed", "pending"):
        _fail(conn, "hold", "", node_id,
              f"node {node_id} is {node['state']}, only proposed|pending can be held")
    conn.execute("UPDATE nodes SET state='blocked', updated_at=? WHERE id=?",
                 (now_iso(), node_id))
    _event(conn, "hold", "", node_id, reason or "held (deferred)")
    conn.commit()


def delegate(conn, node_id, owner, resources="", note=None, check_after=None):
    node = _node_or_fail(conn, "delegate", owner, node_id)
    if node["state"] != "active":
        _fail(conn, "delegate", owner, node_id,
              f"node {node_id} is {node['state']}, only active nodes can be "
              f"delegated to running")
    if node["owner"] and node["owner"] != owner:
        _fail(conn, "delegate", owner, node_id,
              f"node {node_id} is owned by {node['owner']}, not {owner}")
    conn.execute(
        "UPDATE nodes SET state='running', resources=?, note=?, check_after=?, "
        "updated_at=? WHERE id=?",
        (resources or None, note if note is not None else node["note"],
         check_after or None, now_iso(), node_id))
    _event(conn, "delegate", owner, node_id,
           f"resources={resources or '-'} check_after={check_after or '-'}")
    conn.commit()
    return {"id": node_id, "state": "running", "resources": resources or None}


def reactivate(conn, node_id, owner):
    node = _node_or_fail(conn, "reactivate", owner, node_id)
    if node["state"] != "running":
        _fail(conn, "reactivate", owner, node_id,
              f"node {node_id} is {node['state']}, only running nodes can be "
              f"reactivated")
    conn.execute("UPDATE nodes SET state='active', owner=?, updated_at=? "
                 "WHERE id=?", (owner, now_iso(), node_id))
    _event(conn, "reactivate", owner, node_id, "attention reclaimed")
    conn.commit()
    return {"id": node_id, "state": "active", "owner": owner}


def release(conn, node_id, reason=""):
    node = _node_or_fail(conn, "release", "", node_id)
    if node["state"] not in ("active", "blocked"):
        _fail(conn, "release", "", node_id,
              f"node {node_id} is {node['state']}, only active|blocked can be released")
    conn.execute(
        "UPDATE nodes SET state='pending', owner=NULL, updated_at=? WHERE id=?",
        (now_iso(), node_id))
    _event(conn, "release", "", node_id, reason or "released to pending")
    conn.commit()


def note(conn, node_id, text):
    _node_or_fail(conn, "note", "", node_id)
    conn.execute("UPDATE nodes SET note=?, updated_at=? WHERE id=?",
                 (text, now_iso(), node_id))
    _event(conn, "note", "", node_id, text.splitlines()[0] if text else "")
    conn.commit()


def approve(conn, node_id, spec_edit=None):
    node = _node_or_fail(conn, "approve", "", node_id)
    if node["state"] != "proposed":
        _fail(conn, "approve", "", node_id,
              f"node {node_id} is {node['state']}, only proposed can be approved")
    conn.execute(
        "UPDATE nodes SET state='pending', spec=?, updated_at=? WHERE id=?",
        (spec_edit if spec_edit is not None else node["spec"], now_iso(), node_id))
    _event(conn, "approve", "", node_id, "spec edited" if spec_edit else "")
    conn.commit()


def reject(conn, node_id):
    node = _node_or_fail(conn, "reject", "", node_id)
    if node["state"] != "proposed":
        _fail(conn, "reject", "", node_id,
              f"node {node_id} is {node['state']}, only proposed can be rejected")
    conn.execute("UPDATE nodes SET state='rejected', updated_at=? WHERE id=?",
                 (now_iso(), node_id))
    _event(conn, "reject", "", node_id)
    conn.commit()


def announce(conn, text=None, clear=False, owner="", ttl_days=None):
    if clear:
        conn.execute("UPDATE announcements SET active=0 WHERE active=1")
    ann_id = None
    if text:
        expires_at = None
        if ttl_days:
            exp = datetime.now(timezone.utc) + timedelta(days=float(ttl_days))
            expires_at = exp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        cur = conn.execute(
            "INSERT INTO announcements(text, active, expires_at, created_at) "
            "VALUES(?,1,?,?)", (text, expires_at, now_iso()))
        ann_id = cur.lastrowid
    _event(conn, "announce", owner, "",
           (text or "") + (" (cleared)" if clear else ""))
    conn.commit()
    return ann_id


def events(conn, tool=None, owner=None, node_id=None, limit=50):
    clauses, args = [], []
    if tool:
        clauses.append("tool=?")
        args.append(tool)
    if owner:
        clauses.append("owner=?")
        args.append(owner)
    if node_id:
        clauses.append("node_id=?")
        args.append(node_id)
    q = "SELECT * FROM events"
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, int(limit)))
    rows = [dict(r) for r in conn.execute(q, args).fetchall()]
    rows.reverse()
    return rows
