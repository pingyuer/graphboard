import json
import os
import sys
from pathlib import Path

from .base import HostAdapter


class OmpAdapter(HostAdapter):
    name = "omp"

    def agents_dir(self, repo: Path) -> Path:
        return Path(os.path.expanduser(str(repo))) / ".omp" / "agents"

    def render_frontmatter(self, name: str, description: str) -> str:
        return f"""---
name: {name}
description: {description}
---
"""

    def write_config(self, repo: Path, board_dir: Path, project: str) -> str:
        repo = Path(os.path.expanduser(str(repo)))
        board_dir = Path(os.path.expanduser(str(board_dir)))
        mcp_block = {
            "command": sys.executable,
            "args": ["-m", "graphboard.server"],
            "env": {
                "GB_BOARD": str(board_dir),
                "GB_PROJECT": project,
                "GB_REPO": str(repo),
            },
        }
        mcp_file = repo / ".mcp.json"
        if mcp_file.exists():
            try:
                config = json.loads(mcp_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                config = {}
            action = "updated"
        else:
            config = {}
            action = "wrote"

        servers = config.setdefault("mcpServers", {})
        servers["graphboard"] = mcp_block
        mcp_file.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        return action

    def gitignore_entries(self) -> list[str]:
        return [".omp/run/", ".omp/cache/"]

    def next_steps(self, repo: Path) -> str:
        return ("run 'omp' in this directory and talk to the gb conductor (/agent gb) "
                "to define your project workflow.")
