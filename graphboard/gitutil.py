import os
import subprocess
from pathlib import Path


def git_baseline(repo_dir):
    repo = Path(os.path.expanduser(str(repo_dir)))
    if not (repo / ".git").exists():
        return None
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=repo, capture_output=True, text=True, timeout=5)
        if head.returncode != 0:
            return None
        dirty = subprocess.run(["git", "status", "--porcelain"],
                               cwd=repo, capture_output=True, text=True, timeout=5)
        n = len([l for l in dirty.stdout.splitlines() if l.strip()])
        return {"hash": head.stdout.strip(), "dirty": n}
    except (OSError, subprocess.TimeoutExpired):
        return None
