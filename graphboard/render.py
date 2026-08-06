from .core import PRIORITY_DEFAULT

OVERVIEW_BUDGET = 20


def _first_line(text, limit=80):
    if not text:
        return ""
    line = text.strip().splitlines()[0]
    return line if len(line) <= limit else line[:limit] + "..."


def _prio(p):
    return f" [p{p}]" if p is not None and p != PRIORITY_DEFAULT else ""


def _facts_lines(facts):
    if not facts:
        return []
    return ["facts:"] + [f"  - {f['key']}: {f['value']}" for f in facts]


def _messages_lines(messages):
    if not messages:
        return []
    lines = ["messages:"]
    for m in messages:
        to = "" if m.get("audience", "*") == "*" else f" to={m['audience']}"
        lines.append(f"  - [{m['author']}]{to} {m['text']}")
    return lines


def render_pull(result):
    if result.get("claimed") is None:
        counts = result["counts"]
        parts = [f"{k}: {v}" for k, v in counts.items() if v]
        lines = ["nothing pending. " + (", ".join(parts) if parts else "board is empty")]
        if result.get("awaiting_approval"):
            lines.append(f"note: {result['awaiting_approval']} proposed node(s) await "
                         f"human approval - wait or ask, do not start working")
        if result.get("announcements"):
            lines.append("announcements:")
            for a in result["announcements"]:
                lines.append(f"  - [{a['id']}] {a['text']}")
        return "\n".join(lines)
    c = result["claimed"]
    lines = [
        f"claimed: {c['id']}{_prio(c.get('priority'))}",
        f"type: {c['type']}",
        f"summary: {c.get('summary') or _first_line(c.get('spec', ''), 120)}",
        f"full: gb_status id={c['id']} (spec, lineage, outputs, messages)",
    ]
    if c.get("note"):
        lines.append(f"anchor: {c['note']}")
    if c.get("workdir"):
        lines.append(f"workdir: {c['workdir']}")
    if c.get("baseline"):
        lines.append(f"baseline: {c['baseline']} (git sync point - diff against it to re-orient)")
    if c.get("on_event"):
        lines.append(f"triggered_by: {c['on_event']}")
    if result.get("inputs"):
        lines.append("inputs:")
        for i in result["inputs"]:
            suffix = f"  ({i['note']})" if i.get("note") else ""
            lines.append(f"  - {i['path']}{suffix}")
    lines.extend(_messages_lines(result.get("messages")))
    if result.get("announcements"):
        lines.append("announcements:")
        for a in result["announcements"]:
            lines.append(f"  - [{a['id']}] {a['text']}")
    return "\n".join(lines)


def render_submit(result):
    lines = [
        f"{result['id']}: {result['state']} (event: {result['event']}), "
        f"{result['outputs']} outputs recorded"
    ]
    if result.get("reactivated"):
        lines.append(f"reactivated parent: {result['reactivated']} -> pending "
                     f"(all split children done, ready to integrate)")
    for s in result.get("successors", ()):
        lines.append(
            f"successor: {s['id']} ({s['type']}) -> {s['state']} [{s['reason']}]")
    for n in result.get("notices", ()):
        lines.append(f"notice: {n}")
    return "\n".join(lines)


def render_split(result):
    lines = [f"{result['id']}: split -> blocked (owner released)"]
    for c in result.get("children", ()):
        lines.append(
            f"child: {c['id']} ({c['type']}) -> {c['state']} [{c['reason']}]")
    lines.append("when all children are done, this node returns to pending "
                 "for integration")
    return "\n".join(lines)


def render_propose(node_id):
    return f"proposed: {node_id} (awaiting approval)"


def render_status(result):
    if "node" in result:
        n = result["node"]
        lines = [
            f"id: {n['id']}{_prio(n.get('priority'))}",
            f"type: {n['type']}",
            f"state: {n['state']}" + (" (archived)" if n.get("archived") else ""),
            f"owner: {n['owner'] or '-'}",
        ]
        if n.get("summary"):
            lines.append(f"summary: {n['summary']}")
        lines.append(f"spec: {n['spec']}")
        if n.get("note"):
            lines.append(f"anchor: {n['note']}")
        if n.get("resources"):
            lines.append(f"resources: {n['resources']}")
        if n.get("check_after"):
            lines.append(f"check_after: {n['check_after']}")
        if n.get("superseded_by"):
            lines.append(f"superseded_by: {n['superseded_by']}")
        if result.get("parent"):
            p = result["parent"]
            lines.append(f"parent: {p['id']} ({p['type']}, {p['state']})")
        if result.get("children"):
            lines.append("children:")
            for ch in result["children"]:
                lines.append(f"  - {ch['id']} ({ch['type']}, {ch['state']}, on {ch['on_event']})")
        if result.get("outputs"):
            lines.append("outputs:")
            for o in result["outputs"]:
                suffix = f"  ({o['note']})" if o.get("note") else ""
                lines.append(f"  - {o['path']}{suffix}")
        lines.extend(_messages_lines(result.get("messages")))
        return "\n".join(lines)
    counts = result["counts"]
    lines = ["counts: " + ", ".join(f"{k}: {v}" for k, v in counts.items())]
    if result.get("yours"):
        lines.append("your nodes:")
        for n in result["yours"]:
            res = f" res={n['resources']}" if n.get("resources") else ""
            check = f" check_after={n['check_after']}" if n.get("check_after") else ""
            lines.append(f"  - {n['id']} ({n['type']}, {n['state']}){res}{check} "
                         f"{n.get('summary') or ''}".rstrip())
            if n.get("note"):
                lines.append(f"    anchor: {n['note']}")
    if result.get("open"):
        lines.append("open nodes:")
        for n in result["open"][:OVERVIEW_BUDGET - 2]:
            owner = f" [{n['owner']}]" if n.get("owner") else ""
            res = f" res={n['resources']}" if n.get("resources") else ""
            mail = f" ✉{n['msg_count']}" if n.get("msg_count") else ""
            lines.append(f"  - {n['id']} ({n['type']}, {n['state']})"
                         f"{owner}{_prio(n.get('priority'))}{res}{mail} "
                         f"{n.get('summary') or _first_line(n.get('spec',''), 60)}")
        extra = len(result["open"]) - (OVERVIEW_BUDGET - 2)
        if extra > 0:
            lines.append(f"  ... {extra} more")
    return "\n".join(lines)


def render_query(result):
    if not result["nodes"]:
        return "no nodes match"
    lines = []
    for n in result["nodes"]:
        owner = f" [{n['owner']}]" if n.get("owner") else ""
        arch = " (archived)" if n.get("archived") else ""
        mail = f" ✉{n['msg_count']}" if n.get("msg_count") else ""
        lines.append(f"{n['id']} ({n['type']}, {n['state']}){owner}"
                     f"{_prio(n.get('priority'))}{arch}{mail} "
                     f"{n.get('summary') or _first_line(n.get('spec',''), 60)}")
        if n.get("resources"):
            check = f" check_after={n['check_after']}" if n.get("check_after") else ""
            lines.append(f"  resources: {n['resources']}{check}")
        if n["outputs"]:
            outs = ", ".join(o["path"] for o in n["outputs"])
            lines.append(f"  outputs: {outs}")
    if result.get("truncated"):
        lines.append("... (limit reached, narrow the query)")
    return "\n".join(lines)


def render_cancel(node_id):
    return f"canceled: {node_id} (terminal; owner/note preserved for audit)"


def render_hold(node_id):
    return f"held: {node_id} -> blocked (deferred; release to re-queue)"


def render_delegate(result):
    res = f" resources={result['resources']}" if result.get("resources") else ""
    return (f"delegated: {result['id']} -> running{res} (agent detached; "
            f"harvest later via submit, or gb_reactivate to reclaim)")


def render_reactivate(result):
    return (f"reactivated: {result['id']} -> active "
            f"(attention reclaimed by {result['owner']})")


def render_release(node_id):
    return f"released: {node_id} -> pending (owner cleared, anchor note preserved)"


def render_note(node_id):
    return f"note updated: {node_id}"


def render_approve(node_id):
    return f"approved: {node_id} -> pending"


def render_reject(node_id):
    return f"rejected: {node_id}"


def render_announce(ann_id, cleared, audience="*"):
    if ann_id is None:
        return "announcements cleared" if cleared else "nothing to announce"
    to = f" to={audience}" if audience not in ("*", "", None) else ""
    return (f"announced #{ann_id}{to}"
            + (" (previous cleared)" if cleared else ""))


def render_priority(node_id, level):
    return f"priority: {node_id} -> p{level} (pull serves lower numbers first)"


def render_message(node_id, audience):
    to = f" to={audience}" if audience not in ("*", "", None) else ""
    return f"message recorded on {node_id}{to} (delivered at the audience's next pull/status)"


def render_fact_set(key):
    return f"fact set: {key} (injected at every pull)"


def render_fact_remove(key):
    return f"fact removed: {key}"


def render_facts(rows):
    if not rows:
        return "no facts recorded"
    return "\n".join(f"{f['key']}: {f['value']}  "
                     f"(by {f['updated_by']}, {f['updated_at'][:10]})"
                     for f in rows)


def render_summary(node_id):
    return f"summary updated: {node_id}"


def render_charter(action):
    if action == "set":
        return "charter updated (.board/charter.md) - baked into roles at generation"
    return "charter is empty; set it so new roles inherit the project background"


def render_reopen(node_id, prev_state):
    return (f"reopened: {node_id} -> pending (was {prev_state}; reason in events; "
            f"anchor preserved for re-pull)")


def render_archive(node_id, count):
    return (f"archived: {count} node(s) under {node_id} (hidden from live views; "
            f"restore to bring back)")


def render_restore(node_id):
    return f"restored: {node_id} to live views (state unchanged)"


def render_supersede(result):
    approved = " (approved to pending)" if result.get("approved") else ""
    return (f"superseded: {result['old']} -> canceled; "
            f"replacement {result['new']}{approved}")
