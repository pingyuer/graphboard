import argparse
import os
import sys
from pathlib import Path

from . import core, db, doctor, render, roles, scaffold
from .gitutil import git_baseline
from .grammar import (GrammarError, check, grammar_add_rule, grammar_remove_rule,
                      load, load_nodetypes)


class UsageError(Exception):
    pass


def resolve_board(args):
    if getattr(args, "board", None):
        d = Path(os.path.expanduser(args.board))
        if not (d / "graph.db").exists():
            raise UsageError(f"no board at {d}; run: gb init [dir]")
        return d
    env = os.environ.get("GB_BOARD", "")
    if env:
        d = Path(os.path.expanduser(env))
        if not (d / "graph.db").exists():
            raise UsageError(f"GB_BOARD points to {d} but no board there")
        return d
    cur = Path.cwd()
    for d in [cur, *cur.parents]:
        if (d / ".board" / "graph.db").exists():
            return d / ".board"
    raise UsageError("no board found (searched upward from cwd); run: gb init [dir]")


def open_board(args):
    board = resolve_board(args)
    conn = db.connect(board / "graph.db")
    grammar = None
    gpath = board / "transitions.yaml"
    if gpath.exists():
        grammar = load(gpath)
    contracts = load_nodetypes(board / "nodetypes.yaml")
    return conn, grammar, contracts


def cmd_init(args):
    dir_ = args.dir or os.getcwd()
    try:
        result = scaffold.scaffold_project(
            dir_, name=args.name, template=args.template,
            agents=[a.strip() for a in args.agents.split(",") if a.strip()] or ["gb"],
            git=args.git, force=args.force)
    except core.GbError as e:
        raise UsageError(str(e))
    print(f"initialized project '{result['project']}' at {result['repo']}")
    print(f"  board: {result['board']} ({result['board_action']}, "
          f"template: {args.template})")
    for action, path in result["agents"]:
        print(f"  agent {action}: {path}")
    print(f"  AGENTS.md: {result['agents_md']}")
    print(f"  opencode.json: {result['config']}")
    print(f"  git: {result['git']}")
    print("\nnext: open opencode in this directory, switch to the gb role,")
    print("and tell it what this project needs (roles, workflow, first node).")
    return 0


def cmd_list(args):
    conn, _, _ = open_board(args)
    if args.archived:
        rows = conn.execute(
            "SELECT id, type, state, owner, spec FROM nodes WHERE archived=1 "
            "ORDER BY created_at").fetchall()
        if not rows:
            print("no archived nodes")
        for r in rows:
            owner = f" [{r['owner']}]" if r["owner"] else ""
            print(f"{r['id']} ({r['type']}, {r['state']}){owner} "
                  f"{r['spec'].splitlines()[0]}")
        return 0
    if args.state:
        rows = conn.execute(
            "SELECT id, type, state, owner, spec FROM nodes "
            "WHERE state=? AND archived=0 "
            "ORDER BY priority ASC, created_at", (args.state,)).fetchall()
        if not rows:
            print(f"no {args.state} nodes")
        for r in rows:
            owner = f" [{r['owner']}]" if r["owner"] else ""
            print(f"{r['id']} ({r['type']}){owner} {r['spec'].splitlines()[0]}")
        return 0
    print(render.render_status(core.status(conn)))
    return 0


def cmd_show(args):
    conn, _, _ = open_board(args)
    print(render.render_status(core.status(conn, args.id)))
    return 0


def cmd_query(args):
    conn, _, _ = open_board(args)
    result = core.query(conn, type=args.type, state=args.state, under=args.under,
                        owner=args.owner, limit=args.limit,
                        include_archived=args.archived)
    print(render.render_query(result))
    return 0


def cmd_propose(args):
    conn, _, _ = open_board(args)
    nid = core.propose(conn, args.type, args.spec, parent=args.parent,
                       on=args.on, priority=args.priority,
                       summary=args.summary)
    print(render.render_propose(nid))
    return 0


def cmd_summary(args):
    conn, _, _ = open_board(args)
    core.set_summary(conn, args.id, args.text)
    print(render.render_summary(args.id))
    return 0


def cmd_charter(args):
    conn, _, _ = open_board(args)
    if args.text:
        core.charter_set(conn, args.text, by="human")
        print(render.render_charter("set"))
        return 0
    charter = core.charter_get(conn)
    print(charter or render.render_charter("empty"))
    return 0


def cmd_priority(args):
    conn, _, _ = open_board(args)
    core.set_priority(conn, args.id, args.level, reason=args.reason or "")
    print(render.render_priority(args.id, args.level))
    return 0


def cmd_message(args):
    conn, _, _ = open_board(args)
    core.message(conn, args.id, author=args.author or "human", text=args.text,
                 audience=args.audience or "*")
    print(render.render_message(args.id, args.audience or "*"))
    return 0


def cmd_fact(args):
    conn, _, _ = open_board(args)
    if args.fact_cmd == "set":
        core.fact_set(conn, args.key, args.value, by="human")
        print(render.render_fact_set(args.key.strip()))
    elif args.fact_cmd == "remove":
        core.fact_remove(conn, args.key, by="human")
        print(render.render_fact_remove(args.key.strip()))
    else:
        print(render.render_facts(core.facts(conn)))
    return 0


def cmd_reopen(args):
    conn, _, _ = open_board(args)
    prev = core.status(conn, args.id)["node"]["state"]
    core.reopen(conn, args.id, reason=args.reason or "")
    print(render.render_reopen(args.id, prev))
    return 0


def cmd_archive(args):
    conn, _, _ = open_board(args)
    count = core.archive(conn, args.id, under=args.under)
    print(render.render_archive(args.id, count))
    return 0


def cmd_restore(args):
    conn, _, _ = open_board(args)
    core.restore(conn, args.id)
    print(render.render_restore(args.id))
    return 0


def cmd_supersede(args):
    conn, _, _ = open_board(args)
    result = core.supersede(conn, args.old, args.new, reason=args.reason or "")
    print(render.render_supersede(result))
    return 0


def cmd_pull(args):
    conn, _, _ = open_board(args)
    result = core.pull(conn, args.owner, type_filter=args.type)
    if result.get("claimed"):
        baseline = git_baseline(resolve_board(args).parent)
        if baseline:
            dirty = "clean" if baseline["dirty"] == 0 else f"+{baseline['dirty']} dirty files"
            result["claimed"]["baseline"] = f"{baseline['hash']} ({dirty})"
    print(render.render_pull(result))
    return 0


def cmd_submit(args):
    conn, grammar, _ = open_board(args)
    r = core.submit(conn, args.id, owner=args.owner, status=args.status,
                    outputs=core.parse_outputs(args.output),
                    successors=core.parse_successors(args.succ),
                    event=args.event, note=args.note, grammar=grammar)
    print(render.render_submit(r))
    return 0


def cmd_split(args):
    conn, grammar, _ = open_board(args)
    r = core.split(conn, args.id, owner=args.owner,
                   children=core.parse_successors(args.child), grammar=grammar)
    print(render.render_split(r))
    return 0


def cmd_release(args):
    conn, _, _ = open_board(args)
    core.release(conn, args.id, reason=args.reason or "")
    print(render.render_release(args.id))
    return 0


def cmd_cancel(args):
    conn, _, _ = open_board(args)
    core.cancel(conn, args.id, reason=args.reason or "")
    print(render.render_cancel(args.id))
    return 0


def cmd_hold(args):
    conn, _, _ = open_board(args)
    core.hold(conn, args.id, reason=args.reason or "")
    print(render.render_hold(args.id))
    return 0


def cmd_delegate(args):
    conn, _, _ = open_board(args)
    result = core.delegate(conn, args.id, owner=args.owner,
                           resources=args.resources or "",
                           note=args.note or None,
                           check_after=args.check_after or None)
    print(render.render_delegate(result))
    return 0


def cmd_reactivate(args):
    conn, _, _ = open_board(args)
    result = core.reactivate(conn, args.id, owner=args.owner)
    print(render.render_reactivate(result))
    return 0


def cmd_note(args):
    conn, _, _ = open_board(args)
    core.note(conn, args.id, args.text)
    print(render.render_note(args.id))
    return 0


def cmd_approve(args):
    conn, _, _ = open_board(args)
    core.approve(conn, args.id, spec_edit=args.spec_edit)
    print(render.render_approve(args.id))
    return 0


def cmd_reject(args):
    conn, _, _ = open_board(args)
    core.reject(conn, args.id)
    print(render.render_reject(args.id))
    return 0


def cmd_announce(args):
    conn, _, _ = open_board(args)
    ann_id = core.announce(conn, text=args.text, clear=args.clear,
                           ttl_days=args.ttl_days or None,
                           audience=args.audience or "*")
    print(render.render_announce(ann_id, args.clear,
                                 audience=args.audience or "*"))
    return 0


def cmd_grammar_check(args):
    if args.grammar:
        gpath = Path(args.grammar)
        npath = Path(args.nodetypes) if args.nodetypes else None
    else:
        board = resolve_board(args)
        gpath, npath = board / "transitions.yaml", board / "nodetypes.yaml"
        if not gpath.exists():
            raise UsageError(f"no grammar at {gpath}")
    g = load(gpath)
    nodetypes = load_nodetypes(npath) if npath else {}
    findings = check(g, nodetypes)
    if not findings:
        print("grammar OK")
        return 0
    errors = 0
    for level, msg in findings:
        print(f"{level}: {msg}")
        errors += level == "error"
    return 1 if errors else 0


def cmd_grammar_add(args):
    board = resolve_board(args)
    findings = grammar_add_rule(board, args.frm, args.on, args.to,
                                activate=args.activate, budget=args.budget,
                                force=args.force)
    print(f"added: {args.frm} --{args.on}--> {args.to} [{args.activate}]")
    for level, msg in findings:
        print(f"{level}: {msg}")
    return 0


def cmd_grammar_remove(args):
    board = resolve_board(args)
    grammar_remove_rule(board, args.frm, args.on, args.to)
    print(f"removed: {args.frm} --{args.on}--> {args.to}")
    return 0


def cmd_role_new(args):
    repo = Path(os.path.expanduser(args.repo))
    claims = [c.strip() for c in args.claims.split(",") if c.strip()]
    background, contracts = "", {}
    try:
        board = resolve_board(args)
        background, contracts = roles.collect_role_context(board, claims or ["task"])
    except UsageError:
        pass
    content = roles.render_role(
        name=args.name, description=args.desc, claims=claims or ["task"],
        duties=args.duties or "Work the claimed node according to its spec and contract.",
        loading=args.loading or "Start from the node's inputs; use gb_query for anything else needed.",
        outputs=args.outputs or "Code artifacts stay in the repo (commit your own files with explicit "
                                "pathspec before submit); coordination artifacts go to the workdir.",
        done_when=args.done_when or "The node spec's completion criteria are met and outputs are submitted.",
        background=args.background or background, contracts=contracts)
    path = roles.write_role(repo, args.name, content, force=args.force)
    print(f"wrote role: {path}")
    if claims:
        try:
            board = resolve_board(args)
        except UsageError:
            board = None
        if board:
            added = roles.ensure_nodetypes(board, claims, args.desc)
            if added:
                print(f"node types added: {', '.join(added)}")
            print(roles.suggest_grammar_rules(claims))
    return 0


def cmd_role_list(args):
    for r in roles.list_roles(args.repo):
        claims = f" claims: {r['claims']}" if r["claims"] else ""
        print(f"{r['name']}: {r['description']}{claims}")
    return 0


def cmd_log(args):
    conn, _, _ = open_board(args)
    rows = core.events(conn, tool=args.tool, owner=args.owner,
                       node_id=args.node, limit=args.limit)
    if not rows:
        print("no events match")
        return 0
    for r in rows:
        owner = f" [{r['owner']}]" if r["owner"] else ""
        node = f" {r['node_id']}" if r["node_id"] else ""
        detail = f" {r['detail']}" if r["detail"] else ""
        print(f"{r['ts']} {r['tool']}{owner}{node}{detail}")
    return 0


def cmd_doctor(args):
    conn, grammar, _ = open_board(args)
    board = resolve_board(args)
    ok, issues = doctor.run_checks(conn, board, grammar,
                                   stale_hours=args.stale_hours,
                                   orphan_hours=args.orphan_hours)
    print(doctor.render_report(ok, issues))
    return 1 if issues else 0


def cmd_export(args):
    conn, _, _ = open_board(args)
    project = db.get_meta(conn, "project", "board")
    lines = [f"# graphboard export: {project}", ""]
    overview = core.status(conn)
    lines.append("counts: " + ", ".join(f"{k}: {v}" for k, v in overview["counts"].items()))
    lines.append("")
    if overview.get("facts"):
        lines.append("## facts")
        lines.extend(f"- {f['key']}: {f['value']}" for f in overview["facts"])
        lines.append("")
    for state in ("active", "running", "pending", "proposed", "blocked",
                  "done", "rejected", "canceled"):
        rows = conn.execute(
            "SELECT id, type, owner, spec, note, priority FROM nodes "
            "WHERE state=? AND archived=0 "
            "ORDER BY priority ASC, created_at", (state,)).fetchall()
        if not rows:
            continue
        lines.append(f"## {state}")
        for r in rows:
            owner = f" [{r['owner']}]" if r["owner"] else ""
            prio = f" [p{r['priority']}]" if r["priority"] != core.PRIORITY_DEFAULT else ""
            lines.append(f"- {r['id']} ({r['type']}){owner}{prio}: {r['spec']}")
            if r["note"]:
                lines.append(f"  note: {r['note']}")
        lines.append("")
    archived = conn.execute(
        "SELECT COUNT(*) c FROM nodes WHERE archived=1").fetchone()["c"]
    if archived:
        lines.append(f"## archived: {archived} node(s) hidden "
                     f"(gb list --archived to view)")
        lines.append("")
    edges = conn.execute(
        "SELECT from_id, on_event, to_id FROM edges ORDER BY rowid").fetchall()
    if edges:
        lines.append("## edges")
        lines.extend(f"- {e['from_id']} --{e['on_event']}--> {e['to_id']}" for e in edges)
    text = "\n".join(lines) + "\n"
    if args.file:
        Path(args.file).write_text(text, encoding="utf-8")
        print(f"exported to {args.file}")
    else:
        print(text)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="gb", description="graphboard: graph-based task automaton")
    parser.add_argument("--board", help="explicit board directory "
                        "(default: $GB_BOARD, or nearest .board/ upward from cwd)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="scaffold a self-contained project workspace")
    p.add_argument("dir", nargs="?", help="project directory (default: cwd)")
    p.add_argument("--name", help="project name (default: directory basename)")
    p.add_argument("--template", default="minimal",
                   help="grammar starter: minimal|rd-classic|experiment|branching")
    p.add_argument("--agents", default="gb",
                   help="comma-separated agent templates to install (default: gb only)")
    p.add_argument("--git", action="store_true", help="git init if not a repo")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("list", help="show board overview or nodes by state")
    p.add_argument("--state")
    p.add_argument("--archived", action="store_true",
                   help="list archived nodes instead of the live board")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("show", help="show one node with lineage")
    p.add_argument("id")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("query", help="query nodes by type/state/under/owner")
    p.add_argument("--type")
    p.add_argument("--state")
    p.add_argument("--under", help="subtree of this node id (inclusive)")
    p.add_argument("--owner")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--archived", action="store_true",
                   help="include archived nodes")
    p.set_defaults(fn=cmd_query)

    p = sub.add_parser("propose", help="propose a new node (needs approval)")
    p.add_argument("--type", required=True)
    p.add_argument("--spec", required=True)
    p.add_argument("--parent")
    p.add_argument("--on")
    p.add_argument("--priority", type=int, default=None,
                   help="1-9, lower is served first (default 3)")
    p.add_argument("--summary",
                   help="one short line for board views/pull (default: spec's "
                        "first line)")
    p.set_defaults(fn=cmd_propose)

    p = sub.add_parser("summary", help="repair a node's summary (one short line "
                                       "for board views/pull)")
    p.add_argument("id")
    p.add_argument("--text", required=True)
    p.set_defaults(fn=cmd_summary)

    p = sub.add_parser("charter", help="project background baked into role files "
                                       "at generation (show, or pass text to set)")
    p.add_argument("text", nargs="?")
    p.set_defaults(fn=cmd_charter)

    p = sub.add_parser("priority", help="re-prioritize a proposed|pending|blocked "
                                        "node (scheduling hint, not a dependency)")
    p.add_argument("id")
    p.add_argument("level", type=int)
    p.add_argument("--reason")
    p.set_defaults(fn=cmd_priority)

    p = sub.add_parser("message", help="append a directed message to a node "
                                       "(any state; delivered at next pull)")
    p.add_argument("id")
    p.add_argument("--text", required=True)
    p.add_argument("--audience", default="*",
                   help="'*', a role name or an owner name")
    p.add_argument("--author", default="human")
    p.set_defaults(fn=cmd_message)

    p = sub.add_parser("fact", help="project facts (volatile truths injected "
                                    "at every pull)")
    fact_sub = p.add_subparsers(dest="fact_cmd", required=True)
    pf = fact_sub.add_parser("set")
    pf.add_argument("key")
    pf.add_argument("value")
    pf.set_defaults(fn=cmd_fact)
    pf = fact_sub.add_parser("remove")
    pf.add_argument("key")
    pf.set_defaults(fn=cmd_fact)
    pf = fact_sub.add_parser("list")
    pf.set_defaults(fn=cmd_fact)

    p = sub.add_parser("reopen", help="reopen a terminal node back to pending "
                                      "(world changed after it closed)")
    p.add_argument("id")
    p.add_argument("--reason")
    p.set_defaults(fn=cmd_reopen)

    p = sub.add_parser("archive", help="archive terminal node(s) to cold storage "
                                       "(hidden from live views, restorable)")
    p.add_argument("id")
    p.add_argument("--under", action="store_true",
                   help="archive the whole subtree (atomic)")
    p.set_defaults(fn=cmd_archive)

    p = sub.add_parser("restore", help="restore an archived node to live views")
    p.add_argument("id")
    p.set_defaults(fn=cmd_restore)

    p = sub.add_parser("supersede", help="atomically replace old (proposed|pending) "
                                         "with new: cancel old + approve new")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--reason")
    p.set_defaults(fn=cmd_supersede)

    p = sub.add_parser("pull", help="claim the next pending node")
    p.add_argument("--owner", required=True)
    p.add_argument("--type")
    p.set_defaults(fn=cmd_pull)

    p = sub.add_parser("submit", help="finish the active node")
    p.add_argument("id")
    p.add_argument("--owner", required=True)
    p.add_argument("--status", required=True, choices=("done", "blocked"))
    p.add_argument("--event", help="semantic event (default: status)")
    p.add_argument("--note")
    p.add_argument("--output", action="append", metavar="PATH[:NOTE]")
    p.add_argument("--succ", action="append", metavar="TYPE|SPEC")
    p.set_defaults(fn=cmd_submit)

    p = sub.add_parser("split", help="split an active node into smaller children")
    p.add_argument("id")
    p.add_argument("--owner", required=True)
    p.add_argument("--child", action="append", required=True, metavar="TYPE|SPEC")
    p.set_defaults(fn=cmd_split)

    p = sub.add_parser("release", help="release an orphaned active/blocked node "
                                       "back to pending (owner cleared)")
    p.add_argument("id")
    p.add_argument("--reason")
    p.set_defaults(fn=cmd_release)

    p = sub.add_parser("cancel", help="cancel a non-terminal node (superseded/"
                                      "abandoned); terminal, audit preserved")
    p.add_argument("id")
    p.add_argument("--reason")
    p.set_defaults(fn=cmd_cancel)

    p = sub.add_parser("hold", help="defer a proposed|pending node (-> blocked, "
                                    "invisible to pull until released)")
    p.add_argument("id")
    p.add_argument("--reason")
    p.set_defaults(fn=cmd_hold)

    p = sub.add_parser("delegate", help="delegate an active node to autonomous "
                                        "execution (-> running, agent detached)")
    p.add_argument("id")
    p.add_argument("--owner", required=True)
    p.add_argument("--resources", help="held resource labels, e.g. gpu:srv1;machine:srv2")
    p.add_argument("--note", help="how to check it later (tmux/log coords)")
    p.add_argument("--check-after", dest="check_after",
                   help="when to come back and harvest (ISO time)")
    p.set_defaults(fn=cmd_delegate)

    p = sub.add_parser("reactivate", help="reclaim a running node's attention "
                                          "(-> active, caller becomes owner)")
    p.add_argument("id")
    p.add_argument("--owner", required=True)
    p.set_defaults(fn=cmd_reactivate)

    p = sub.add_parser("note", help="replace a node's anchor note")
    p.add_argument("id")
    p.add_argument("--text", required=True)
    p.set_defaults(fn=cmd_note)

    p = sub.add_parser("approve", help="activate a proposed node")
    p.add_argument("id")
    p.add_argument("--spec-edit")
    p.set_defaults(fn=cmd_approve)

    p = sub.add_parser("reject", help="reject a proposed node")
    p.add_argument("id")
    p.set_defaults(fn=cmd_reject)

    p = sub.add_parser("announce", help="broadcast to agents")
    p.add_argument("text", nargs="?")
    p.add_argument("--clear", action="store_true")
    p.add_argument("--ttl-days", dest="ttl_days", type=float, default=0,
                   help="auto-expire after N days (default: never)")
    p.add_argument("--audience", default="*",
                   help="'*', a role name or an owner name (default: everyone)")
    p.set_defaults(fn=cmd_announce)

    p = sub.add_parser("grammar", help="grammar inspection and structured editing")
    g_sub = p.add_subparsers(dest="grammar_cmd", required=True)
    pg = g_sub.add_parser("check", help="static checks on the transition grammar")
    pg.add_argument("--grammar", help="explicit grammar file (default: board's)")
    pg.add_argument("--nodetypes", help="explicit nodetypes file")
    pg.set_defaults(fn=cmd_grammar_check)
    pg = g_sub.add_parser("add", help="add a transition rule (validated before write)")
    pg.add_argument("--from", dest="frm", required=True)
    pg.add_argument("--on", required=True)
    pg.add_argument("--to", required=True)
    pg.add_argument("--activate", choices=("auto", "approve"), default="approve")
    pg.add_argument("--budget", type=int, default=0)
    pg.add_argument("--force", action="store_true",
                    help="accept a closed cycle without root (seedable via propose only)")
    pg.set_defaults(fn=cmd_grammar_add)
    pg = g_sub.add_parser("remove", help="remove a transition rule")
    pg.add_argument("--from", dest="frm", required=True)
    pg.add_argument("--on", required=True)
    pg.add_argument("--to", required=True)
    pg.set_defaults(fn=cmd_grammar_remove)

    p = sub.add_parser("role", help="role management")
    role_sub = p.add_subparsers(dest="role_cmd", required=True)
    pr = role_sub.add_parser("new", help="generate a role file from the paradigm")
    pr.add_argument("name")
    pr.add_argument("--repo", required=True)
    pr.add_argument("--desc", required=True)
    pr.add_argument("--claims", default="", help="comma-separated node types")
    pr.add_argument("--duties")
    pr.add_argument("--loading")
    pr.add_argument("--outputs")
    pr.add_argument("--done-when", dest="done_when")
    pr.add_argument("--background", default="",
                    help="project background (default: the board charter)")
    pr.add_argument("--force", action="store_true")
    pr.set_defaults(fn=cmd_role_new)
    pr = role_sub.add_parser("list", help="list roles in a repo")
    pr.add_argument("--repo", required=True)
    pr.set_defaults(fn=cmd_role_list)

    p = sub.add_parser("log", help="show the event audit trail")
    p.add_argument("--tool")
    p.add_argument("--owner")
    p.add_argument("--node")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("doctor", help="read-only consistency health check")
    p.add_argument("--stale-hours", type=float, default=24.0)
    p.add_argument("--orphan-hours", type=float, default=4.0)
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("export", help="dump the graph as markdown")
    p.add_argument("file", nargs="?")
    p.set_defaults(fn=cmd_export)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (UsageError, core.GbError, GrammarError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
