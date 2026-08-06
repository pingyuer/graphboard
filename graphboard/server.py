import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from mcp.server.mcpserver import MCPServer

from . import core, db
from .gitutil import git_baseline
from .grammar import GrammarError, load, load_nodetypes

INSTRUCTIONS = """graphboard coordinates work as a task graph.
1 Start work with gb_pull using an owner name in role-instance format (e.g. impl-a); claim a node, work only on it. Pull serves lower priority numbers first; facts (volatile project truths) are injected at every pull.
2 Load context on demand: the node's inputs plus what gb_query finds relevant. Never roam the board.
3 Track progress with gb_note (your own nodes only - the anchor is owner-writable); finish with gb_submit (declare successors when the workflow expects them). If a node grows too big, gb_split it into self-contained children.
4 If lost, after a session restart or context compaction: gb_status with your owner name first (shows your active/running nodes); gb_doctor checks board health.
5 Approval, announcements, messages, facts, roles and the grammar belong to the gb conductor role and the human; never act beyond the current node."""


def _resolve_board_dir():
    b = os.environ.get("GB_BOARD", "")
    if b:
        return Path(os.path.expanduser(b))
    home = os.environ.get("GB_HOME", str(Path.home() / "research" / "board"))
    project = os.environ.get("GB_PROJECT", "")
    if not project:
        raise core.GbError("neither GB_BOARD nor GB_PROJECT environment variable is set")
    return Path(os.path.expanduser(home)) / project


def _project_paths():
    d = _resolve_board_dir()
    if not (d / "graph.db").exists():
        raise core.GbError(
            f"no board at {d}; the gb role can create it with gba_bootstrap, "
            f"or the human can run: gb init")
    return d


def _repo():
    repo = os.environ.get("GB_REPO", "")
    if not repo:
        raise core.GbError("GB_REPO environment variable is not set")
    return Path(os.path.expanduser(repo))


_cache = {}


def _conn():
    return db.connect(_project_paths() / "graph.db")


def _grammar_and_contracts():
    d = _project_paths()
    out = []
    for name, loader in (("grammar", load), ("contracts", load_nodetypes)):
        path = d / ("transitions.yaml" if name == "grammar" else "nodetypes.yaml")
        mtime = path.stat().st_mtime if path.exists() else None
        cache_key = (name, str(path))
        entry = _cache.get(cache_key)
        if entry is None or entry[0] != mtime:
            value = loader(path) if path.exists() else (None if name == "grammar" else {})
            _cache[cache_key] = (mtime, value)
            entry = _cache[cache_key]
        out.append(entry[1])
    return out


LOG_MAX_BYTES = 1024 * 1024


def _rotate_log(log_path):
    try:
        if log_path.exists() and log_path.stat().st_size > LOG_MAX_BYTES:
            backup = log_path.with_suffix(".log.1")
            if backup.exists():
                backup.unlink()
            log_path.rename(backup)
    except OSError:
        pass


def _log_call(tool, args, result, error):
    if os.environ.get("GB_DEBUG") == "0":
        return
    try:
        board = _project_paths()
    except core.GbError:
        return
    verbose = os.environ.get("GB_DEBUG") == "verbose"
    entry = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "tool": tool,
        "ok": not error,
    }
    if verbose:
        entry["args"] = args
        entry["result"] = str(result)[:2000]
    else:
        entry["args"] = {k: (str(v)[:80] if v else v) for k, v in args.items()}
        if error:
            entry["result"] = str(result)[:200]
    log_path = board / "server.log"
    try:
        _rotate_log(log_path)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _summarize_args(kwargs):
    return {k: v for k, v in kwargs.items() if v not in ("", 0, None, False)}


def _guard(tool, kwargs, fn):
    conn = None
    args = _summarize_args(kwargs)
    try:
        conn = _conn()
        result = fn(conn)
        _log_call(tool, args, result, error=False)
        return result
    except (core.GbError, GrammarError) as e:
        result = f"error: {e}"
        _log_call(tool, args, result, error=True)
        return result
    finally:
        if conn is not None:
            conn.close()


def _guard_plain(tool, kwargs, fn):
    args = _summarize_args(kwargs)
    try:
        result = fn()
        _log_call(tool, args, result, error=False)
        return result
    except (core.GbError, GrammarError) as e:
        result = f"error: {e}"
        _log_call(tool, args, result, error=True)
        return result


def _baseline_str():
    repo = os.environ.get("GB_REPO", "")
    if not repo:
        repo = _project_paths().parent
    b = git_baseline(repo)
    if b is None:
        return None
    dirty = "clean" if b["dirty"] == 0 else f"+{b['dirty']} dirty files"
    return f"{b['hash']} ({dirty})"


server = MCPServer(name="graphboard", instructions=INSTRUCTIONS)

infra = SimpleNamespace(
    guard=_guard,
    guard_plain=_guard_plain,
    project_paths=_project_paths,
    resolve_board_dir=_resolve_board_dir,
    repo=_repo,
    grammar_and_contracts=_grammar_and_contracts,
    baseline_str=_baseline_str,
)

from . import tools_governance, tools_work  # noqa: E402

tools_work.register(server, infra)
tools_governance.register(server, infra)


def main():
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
