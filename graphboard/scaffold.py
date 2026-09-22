import json
import os
import re
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

CONTROL_PLANE_EDIT_DENIALS = {
    ".board/*": "deny",
    ".opencode/agents/*": "deny",
    "opencode.json": "deny",
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


from .hosts import get_adapter, OpencodeAdapter


def install_agents(repo, names, force=False, host="auto"):
    repo = Path(os.path.expanduser(str(repo)))
    adapter = get_adapter(host, repo=repo)
    agents_dir = adapter.agents_dir(repo)
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
        content = src.read_text(encoding="utf-8")
        if adapter.name == "omp":
            content = re.sub(r"^mode:\s*primary\s*$", f"name: {name}", content, flags=re.MULTILINE)
        dst.write_text(content, encoding="utf-8")
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
    return OpencodeAdapter().write_config(repo, board_dir, project)


def ensure_gitignore(repo, extra_lines=None):
    repo = Path(os.path.expanduser(str(repo)))
    gi = repo / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    lines = existing.splitlines()
    required = list(GITIGNORE_LINES)
    if extra_lines:
        for l in extra_lines:
            if l not in required:
                required.append(l)
    missing = [l for l in required if l not in lines]
    if not missing:
        return False
    body = existing.rstrip()
    if body:
        body += "\n"
    gi.write_text(body + "\n".join(missing) + "\n", encoding="utf-8")
    return True


def scaffold_project(dir, name=None, template="minimal", agents=("gb",),
                     git=False, force=False, host="auto"):
    repo = Path(os.path.expanduser(str(dir))).resolve()
    repo.mkdir(parents=True, exist_ok=True)
    project = name or repo.name
    board_dir, board_action = init_board(repo / ".board", template=template,
                                         force=force)
    conn = db.connect(board_dir / "graph.db")
    db.set_meta(conn, "project", project)
    conn.close()

    adapter = get_adapter(host, repo=repo)
    agent_results = install_agents(repo, agents, force=force, host=adapter.name)
    agents_md_action = write_agents_md(repo)
    config_action = adapter.write_config(repo, board_dir, project)
    git_action = "skip"
    if (repo / ".git").exists():
        ensure_gitignore(repo, extra_lines=adapter.gitignore_entries())
        git_action = "gitignore"
    elif git:
        subprocess.run(["git", "init"], cwd=repo, check=True,
                       capture_output=True)
        ensure_gitignore(repo, extra_lines=adapter.gitignore_entries())
        git_action = "init"
    return {"repo": repo, "project": project, "board": board_dir,
            "board_action": board_action, "agents": agent_results,
            "agents_md": agents_md_action, "config": config_action,
            "git": git_action, "host": adapter.name}
