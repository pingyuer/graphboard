import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import db
from .core import GbError

TEMPLATES_DIR = Path(__file__).parent / "templates"

GITIGNORE_LINES = [".board/*.db", ".board/*.db-wal", ".board/*.db-shm",
                   ".board/server.log", ".opencode/node_modules/"]

GIT_BASH_DENIALS = {
    "git push*": "deny",
    "git rebase*": "deny",
    "git merge*": "deny",
    "git reset --hard*": "deny",
    "git checkout -b*": "deny",
    "git switch*": "deny",
    "git add -A*": "deny",
    "git add --all*": "deny",
    "git commit -a*": "deny",
    "git commit --all*": "deny",
}


def available_templates():
    return sorted(p.name[len("tmpl-"):-len(".yaml")]
                  for p in TEMPLATES_DIR.glob("tmpl-*.yaml"))


def available_agent_templates():
    return sorted(p.stem for p in (TEMPLATES_DIR / "agents").glob("*.md"))


def init_board(board_dir, template="minimal", force=False):
    board_dir = Path(os.path.expanduser(str(board_dir)))
    tmpl = TEMPLATES_DIR / f"tmpl-{template}.yaml"
    if not tmpl.exists():
        raise GbError(f"unknown template '{template}'; available: {available_templates()}")
    if (board_dir / "graph.db").exists():
        if not force:
            return board_dir, "kept"
        for suffix in ("", "-wal", "-shm"):
            f = board_dir / f"graph.db{suffix}"
            if f.exists():
                f.unlink()
    board_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(tmpl, board_dir / "transitions.yaml")
    nt = TEMPLATES_DIR / f"nodetypes-{template}.yaml"
    if nt.exists():
        shutil.copy(nt, board_dir / "nodetypes.yaml")
    else:
        (board_dir / "nodetypes.yaml").write_text("types: {}\n", encoding="utf-8")
    conn = db.connect(board_dir / "graph.db")
    db.set_meta(conn, "template", template)
    conn.close()
    return board_dir, ("reinit" if force else "created")


def install_agents(repo, names, force=False):
    repo = Path(os.path.expanduser(str(repo)))
    agents_dir = repo / ".opencode" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for name in names:
        src = TEMPLATES_DIR / "agents" / f"{name}.md"
        if not src.exists():
            raise GbError(f"no agent template named '{name}'; "
                          f"available: {available_agent_templates()}")
        dst = agents_dir / f"{name}.md"
        if dst.exists() and not force:
            results.append(("skip", dst))
            continue
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        results.append(("wrote", dst))
    return results


def write_agents_md(repo):
    repo = Path(os.path.expanduser(str(repo)))
    tpl = (TEMPLATES_DIR / "AGENTS.md.tpl").read_text(encoding="utf-8")
    target = repo / "AGENTS.md"
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if "graphboard" in existing:
            return "skip"
        target.write_text(existing.rstrip() + "\n\n" + tpl, encoding="utf-8")
        return "append"
    target.write_text(tpl, encoding="utf-8")
    return "wrote"


def write_opencode_config(repo, board_dir, project):
    repo = Path(os.path.expanduser(str(repo)))
    board_dir = Path(os.path.expanduser(str(board_dir)))
    mcp_block = {
        "type": "local",
        "command": [sys.executable, "-m", "graphboard.server"],
        "enabled": True,
        "environment": {"GB_BOARD": str(board_dir), "GB_PROJECT": project,
                        "GB_REPO": str(repo)},
    }
    oc = repo / "opencode.json"
    if oc.exists():
        try:
            config = json.loads(oc.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            snippet = json.dumps({
                "mcp": {"graphboard": mcp_block},
                "tools": {"gba_*": False},
                "agent": {"gb": {"tools": {"gba_*": True}}},
            }, indent=2)
            fallback = repo / ".opencode" / "graphboard-mcp.snippet.json"
            fallback.parent.mkdir(parents=True, exist_ok=True)
            fallback.write_text(snippet, encoding="utf-8")
            return f"snippet:{fallback}"
    else:
        config = {}
    config.setdefault("mcp", {})["graphboard"] = mcp_block
    config.setdefault("tools", {})["gba_*"] = False
    gb_cfg = config.setdefault("agent", {}).setdefault("gb", {})
    gb_cfg.setdefault("tools", {})["gba_*"] = True
    bash_perm = config.setdefault("permission", {}).setdefault("bash", {})
    for pattern, action in GIT_BASH_DENIALS.items():
        bash_perm.setdefault(pattern, action)
    oc.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return "wrote"


def ensure_gitignore(repo):
    repo = Path(os.path.expanduser(str(repo)))
    gi = repo / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    lines = existing.splitlines()
    missing = [l for l in GITIGNORE_LINES if l not in lines]
    if not missing:
        return False
    body = existing.rstrip()
    if body:
        body += "\n"
    gi.write_text(body + "\n".join(missing) + "\n", encoding="utf-8")
    return True


def scaffold_project(dir, name=None, template="minimal", agents=("gb",),
                     git=False, force=False):
    repo = Path(os.path.expanduser(str(dir))).resolve()
    repo.mkdir(parents=True, exist_ok=True)
    project = name or repo.name
    board_dir, board_action = init_board(repo / ".board", template=template,
                                         force=force)
    conn = db.connect(board_dir / "graph.db")
    db.set_meta(conn, "project", project)
    conn.close()
    agent_results = install_agents(repo, agents, force=force)
    agents_md_action = write_agents_md(repo)
    config_action = write_opencode_config(repo, board_dir, project)
    git_action = "skip"
    if (repo / ".git").exists():
        ensure_gitignore(repo)
        git_action = "gitignore"
    elif git:
        subprocess.run(["git", "init"], cwd=repo, check=True,
                       capture_output=True)
        ensure_gitignore(repo)
        git_action = "init"
    return {"repo": repo, "project": project, "board": board_dir,
            "board_action": board_action, "agents": agent_results,
            "agents_md": agents_md_action, "config": config_action,
            "git": git_action}
