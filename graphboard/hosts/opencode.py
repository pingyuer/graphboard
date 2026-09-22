import json
import os
import sys
from pathlib import Path

from .base import HostAdapter

GIT_BASH_DENIALS = {
    "git push*": "deny",
    "git pull*": "deny",
    "git fetch*": "deny",
    "git merge*": "deny",
    "git rebase*": "deny",
    "git checkout*": "deny",
    "git switch*": "deny",
    "git branch -D*": "deny",
    "git branch -d*": "deny",
    "git reset --hard*": "deny",
    "git clean -f*": "deny",
    "git commit -a*": "deny",
    "git add -A*": "deny",
    "git add --all*": "deny",
    "git add .*": "deny",
}

CONTROL_PLANE_EDIT_DENIALS = {
    ".board/*": "deny",
    ".opencode/agents/*": "deny",
    "opencode.json": "deny",
}


class OpencodeAdapter(HostAdapter):
    name = "opencode"

    def agents_dir(self, repo: Path) -> Path:
        return Path(os.path.expanduser(str(repo))) / ".opencode" / "agents"

    def render_frontmatter(self, name: str, description: str) -> str:
        return f"""---
description: {description}
mode: primary
---
"""

    def write_config(self, repo: Path, board_dir: Path, project: str) -> str:
        repo = Path(os.path.expanduser(str(repo)))
        board_dir = Path(os.path.expanduser(str(board_dir)))
        mcp_block = {
            "type": "local",
            "command": [sys.executable, "-m", "graphboard.server"],
            "enabled": True,
            "environment": {
                "GB_BOARD": str(board_dir),
                "GB_PROJECT": project,
                "GB_REPO": str(repo),
            },
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
                    "permission": {"edit": CONTROL_PLANE_EDIT_DENIALS},
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
        perm = config.setdefault("permission", {})
        bash_perm = perm.setdefault("bash", {})
        for pattern, action in GIT_BASH_DENIALS.items():
            bash_perm.setdefault(pattern, action)
        edit_perm = perm.get("edit")
        if not isinstance(edit_perm, dict):
            edit_perm = {} if edit_perm is None else {"*": edit_perm}
            perm["edit"] = edit_perm
        for pattern, action in CONTROL_PLANE_EDIT_DENIALS.items():
            edit_perm.setdefault(pattern, action)
        oc.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        return "wrote"

    def gitignore_entries(self) -> list[str]:
        return [".opencode/node_modules/"]

    def next_steps(self, repo: Path) -> str:
        return ("open opencode in this directory, switch to the gb role,\n"
                "and tell it what this project needs (roles, workflow, first node).")
