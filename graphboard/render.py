OVERVIEW_BUDGET = 20


def _first_line(text, limit=80):
    if not text:
        return ""
    line = text.strip().splitlines()[0]
    return line if len(line) <= limit else line[:limit] + "..."


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
        f"claimed: {c['id']}",
        f"type: {c['type']}",
        f"spec: {c['spec']}",
    ]
    if c.get("note"):
        lines.append(f"note: {c['note']}")
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
    if result.get("contract"):
        lines.append("contract:")
        lines.extend("  " + l for l in result["contract"].strip().splitlines())
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
            f"id: {n['id']}",
            f"type: {n['type']}",
            f"state: {n['state']}",
            f"owner: {n['owner'] or '-'}",
            f"spec: {n['spec']}",
        ]
        if n.get("note"):
            lines.append(f"note: {n['note']}")
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
        return "\n".join(lines)
    counts = result["counts"]
    lines = ["counts: " + ", ".join(f"{k}: {v}" for k, v in counts.items())]
    if result.get("open"):
        lines.append("open nodes:")
        for n in result["open"][:OVERVIEW_BUDGET - 2]:
            owner = f" [{n['owner']}]" if n.get("owner") else ""
            lines.append(f"  - {n['id']} ({n['type']}, {n['state']}){owner} "
                         f"{_first_line(n['spec'], 60)}")
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
        lines.append(f"{n['id']} ({n['type']}, {n['state']}){owner} "
                     f"{_first_line(n['spec'], 60)}")
        if n["outputs"]:
            outs = ", ".join(o["path"] for o in n["outputs"])
            lines.append(f"  outputs: {outs}")
    if result.get("truncated"):
        lines.append("... (limit reached, narrow the query)")
    return "\n".join(lines)


def render_release(node_id):
    return f"released: {node_id} -> pending (owner cleared, anchor note preserved)"


def render_note(node_id):
    return f"note updated: {node_id}"


def render_approve(node_id):
    return f"approved: {node_id} -> pending"


def render_reject(node_id):
    return f"rejected: {node_id}"


def render_announce(ann_id, cleared):
    if ann_id is None:
        return "announcements cleared" if cleared else "nothing to announce"
    return f"announced #{ann_id}" + (" (previous cleared)" if cleared else "")
