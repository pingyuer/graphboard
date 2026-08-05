import os
import re
from pathlib import Path

from .core import GbError
from .grammar import declare_nodetype


def render_role(name, description, claims, duties, loading, outputs, done_when):
    claims_line = ", ".join(claims) if isinstance(claims, (list, tuple)) else claims
    return f"""---
description: {description}
mode: primary
---

You are the {name} role.

Claims: nodes of type {claims_line}.

Duties:
{duties.strip()}

Loading:
{loading.strip()}

Outputs:
{outputs.strip()}

Done when:
{done_when.strip()}
"""


def write_role(repo, name, content, force=False):
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        raise GbError(f"role name must be lowercase alphanumeric with hyphens: {name!r}")
    repo = Path(os.path.expanduser(str(repo)))
    if not repo.is_dir():
        raise GbError(f"repo directory not found: {repo}")
    agents_dir = repo / ".opencode" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    dst = agents_dir / f"{name}.md"
    if dst.exists() and not force:
        raise GbError(f"role already exists: {dst} (use force to overwrite)")
    dst.write_text(content, encoding="utf-8")
    return dst


def ensure_nodetypes(board_dir, claims, contract):
    return [t for t in claims if declare_nodetype(board_dir, t, contract)]


def suggest_grammar_rules(claims):
    lines = []
    for t in claims:
        lines.append(f'  - {{"from": {t}, "on": done, "to": <NEXT_TYPE>, activate: approve}}')
    return "suggested transitions to add to transitions.yaml:\n" + "\n".join(lines)


def list_roles(repo):
    repo = Path(os.path.expanduser(str(repo)))
    agents_dir = repo / ".opencode" / "agents"
    roles = []
    for p in sorted(agents_dir.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        desc = ""
        m = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
        if m:
            desc = m.group(1).strip()
        claims = ""
        m = re.search(r"^Claims:\s*(.+)$", text, re.MULTILINE)
        if m:
            claims = m.group(1).strip()
        roles.append({"name": p.stem, "description": desc, "claims": claims})
    return roles
