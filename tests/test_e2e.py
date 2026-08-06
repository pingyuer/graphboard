from graphboard import cli, db


def run(board, *argv):
    code = cli.main(["--board", board, *argv])
    assert code == 0, f"gb {' '.join(argv)} exited {code}"
    return code


def init_proj(tmp_path, name, template="minimal"):
    projdir = tmp_path / name
    assert cli.main(["init", str(projdir), "--template", template]) == 0
    return str(projdir / ".board")


def node_by_type(board, ntype, state=None):
    conn = db.connect(f"{board}/graph.db")
    q, args = "SELECT id, state FROM nodes WHERE type=?", [ntype]
    if state:
        q += " AND state=?"
        args.append(state)
    row = conn.execute(q + " ORDER BY created_at DESC", args).fetchone()
    conn.close()
    assert row, f"no {ntype} node in state {state}"
    return row["id"]


def open_states(board):
    conn = db.connect(f"{board}/graph.db")
    rows = conn.execute(
        "SELECT COUNT(*) c FROM nodes WHERE state IN "
        "('pending','active','proposed','blocked')").fetchone()
    conn.close()
    return rows["c"]


def test_full_rd_classic_chain(tmp_path, capsys):
    board = init_proj(tmp_path, "demo", "rd-classic")
    run(board, "grammar", "check")
    out = capsys.readouterr().out
    assert "grammar OK" in out

    run(board, "propose", "--type", "proposal",
        "--spec", "add date parser with falsifiable criteria")
    p1 = node_by_type(board, "proposal", "proposed")
    run(board, "approve", p1)

    run(board, "pull", "--owner", "prop-agent")
    run(board, "submit", p1, "--owner", "prop-agent",
        "--status", "done", "--output", "out/proposal.md:v1",
        "--succ", "implementation|build the parser")
    i1 = node_by_type(board, "implementation", "proposed")
    run(board, "approve", i1)

    run(board, "pull", "--owner", "impl-agent")
    run(board, "submit", i1, "--owner", "impl-agent",
        "--status", "done", "--output", "out/parser.py",
        "--succ", "acceptance|verify against criteria")
    a1 = node_by_type(board, "acceptance", "pending")

    run(board, "pull", "--owner", "acc-agent")
    run(board, "submit", a1, "--owner", "acc-agent",
        "--status", "done", "--event", "fail", "--output", "out/verdict.md",
        "--succ", "implementation|rework: timezone cases fail")
    i2 = node_by_type(board, "implementation", "pending")

    run(board, "pull", "--owner", "impl-agent")
    run(board, "note", i2, "--text", "fixing tz cases")
    run(board, "submit", i2, "--owner", "impl-agent",
        "--status", "done", "--output", "out/parser.py:v2",
        "--succ", "acceptance|re-verify")
    a2 = node_by_type(board, "acceptance", "pending")

    run(board, "pull", "--owner", "acc-agent")
    run(board, "submit", a2, "--owner", "acc-agent",
        "--status", "done", "--output", "out/verdict2.md:all pass")

    assert open_states(board) == 0
    conn = db.connect(f"{board}/graph.db")
    done = conn.execute("SELECT COUNT(*) c FROM nodes WHERE state='done'").fetchone()["c"]
    edges = conn.execute("SELECT COUNT(*) c FROM edges").fetchone()["c"]
    conn.close()
    assert done == 5 and edges == 4

    run(board, "export")
    out = capsys.readouterr().out
    assert "graphboard export: demo" in out


def test_branching_scenario(tmp_path, capsys):
    board = init_proj(tmp_path, "branch", "branching")
    run(board, "grammar", "check")
    assert "grammar OK" in capsys.readouterr().out

    run(board, "propose", "--type", "plan",
        "--spec", "innovation X: three candidate approaches")
    plan = node_by_type(board, "plan", "proposed")
    run(board, "approve", plan)
    run(board, "pull", "--owner", "arch")
    capsys.readouterr()
    run(board, "submit", plan, "--owner", "arch",
        "--status", "done", "--output", "out/plan.md",
        "--succ", "implementation|approach A: adapt existing parser",
        "--succ", "implementation|approach B: rewrite from scratch")
    out = capsys.readouterr().out
    impls = [l.split()[1] for l in out.splitlines() if l.startswith("successor:")]
    assert len(impls) == 2

    for i in impls:
        run(board, "approve", i)
    capsys.readouterr()
    run(board, "pull", "--owner", "impl-a")
    first = capsys.readouterr().out.splitlines()[0]
    run(board, "pull", "--owner", "impl-b")
    second = capsys.readouterr().out.splitlines()[0]
    assert impls[0] in first and impls[1] in second or \
           impls[1] in first and impls[0] in second

    conn = db.connect(f"{board}/graph.db")
    ownership = {r["id"]: r["owner"] for r in conn.execute(
        "SELECT id, owner FROM nodes WHERE type='implementation'").fetchall()}
    conn.close()
    for i in impls:
        run(board, "submit", i,
            "--owner", ownership[i],
            "--status", "done", "--output", f"out/{i}.md:report")

    run(board, "propose", "--type", "review",
        "--spec", f"review both implementations under {plan}")
    review = node_by_type(board, "review", "proposed")
    run(board, "approve", review)
    run(board, "pull", "--owner", "review-a")
    capsys.readouterr()
    run(board, "query", "--under", plan,
        "--type", "implementation", "--state", "done")
    out = capsys.readouterr().out
    assert all(i in out for i in impls)

    run(board, "submit", review, "--owner", "review-a",
        "--status", "done", "--output", "out/verdict.md: A passes",
        "--succ", "harvest|collect round one")
    harvest = node_by_type(board, "harvest", "proposed")
    run(board, "approve", harvest)
    run(board, "pull", "--owner", "arch")
    capsys.readouterr()
    run(board, "submit", harvest, "--owner", "arch",
        "--status", "done", "--output", "out/summary.md",
        "--succ", "plan|round two: refine approach A")
    out = capsys.readouterr().out
    assert "-> proposed [grammar approve]" in out

    conn = db.connect(f"{board}/graph.db")
    row = conn.execute(
        "SELECT COUNT(*) c FROM nodes WHERE state IN "
        "('pending','active','blocked')").fetchone()
    proposed = conn.execute(
        "SELECT COUNT(*) c FROM nodes WHERE state='proposed'").fetchone()["c"]
    conn.close()
    assert row["c"] == 0 and proposed == 1


def test_announce_flow_via_cli(tmp_path, capsys):
    board = init_proj(tmp_path, "demo", "minimal")
    run(board, "announce", "log all random seeds")
    run(board, "propose", "--type", "task", "--spec", "t1")
    nid = node_by_type(board, "task", "proposed")
    run(board, "approve", nid)
    capsys.readouterr()
    run(board, "pull", "--owner", "w1")
    assert "log all random seeds" in capsys.readouterr().out
    run(board, "pull", "--owner", "w1")
    assert "nothing pending" in capsys.readouterr().out


def test_init_rejects_unknown_template(tmp_path):
    code = cli.main(["init", str(tmp_path / "demo"), "--template", "nope"])
    assert code == 1


def test_grammar_check_flags_auto_cycle(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "default: approve\n"
        "transitions:\n"
        '  - {"from": a, "on": done, "to": b, activate: auto}\n'
        '  - {"from": b, "on": done, "to": a, activate: auto}\n')
    code = cli.main(["grammar", "check", "--grammar", str(bad)])
    assert code == 1
    assert "auto cycle" in capsys.readouterr().out


def test_board_discovered_upward(tmp_path, monkeypatch, capsys):
    init_proj(tmp_path, "demo", "minimal")
    sub = tmp_path / "demo" / "src" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    monkeypatch.delenv("GB_BOARD", raising=False)
    assert cli.main(["list"]) == 0
    assert "counts:" in capsys.readouterr().out


def test_machine_migration_incident_scenario(tmp_path, capsys):
    board = init_proj(tmp_path, "incident", "minimal")

    # conductor seeds environment facts before work starts
    run(board, "fact", "set", "gpu-ports", "31431/31531")
    run(board, "fact", "set", "mlflow", "http://172.16.240.77:5000")

    # round 1: design -> experiment, worker delegates a long GPU job
    run(board, "propose", "--type", "design", "--spec", "design the re-eval")
    d1 = node_by_type(board, "design", "proposed")
    run(board, "approve", d1)
    run(board, "pull", "--owner", "design-a")
    capsys.readouterr()
    run(board, "pull", "--owner", "design-a")
    assert "gpu-ports: 31431/31531" in capsys.readouterr().out
    capsys.readouterr()
    run(board, "submit", d1, "--owner", "design-a", "--status", "done",
        "--output", "out/design.md",
        "--succ", "experiment|re-eval 22 ckpts",
        "--succ", "experiment|writeup polish")
    out = capsys.readouterr().out
    succs = [l.split()[1] for l in out.splitlines()
             if l.startswith("successor:")]
    assert len(succs) == 2
    e1, e2_declared = succs
    run(board, "approve", e1)
    run(board, "approve", e2_declared)

    run(board, "pull", "--owner", "exp-a")
    capsys.readouterr()
    run(board, "note", e1, "--text", "tmux wp3_reeval @31431 launched")
    run(board, "delegate", e1, "--owner", "exp-a", "--resources", "gpu:31431",
        "--note", "tmux wp3_reeval @31431", "--check-after",
        "2099-01-01T00:00:00Z")

    # incident: the machine migrates, tmux dies AFTER submit harvested early.
    # conductor updates facts, repairs the graph, directs the worker.
    run(board, "submit", e1, "--owner", "exp-a", "--status", "done",
        "--output", "out/partial.md:only 9/22 ckpts done")
    run(board, "fact", "set", "gpu-ports", "32217/30318")
    run(board, "announce", "machine migrated; check your tasks",
        "--audience", "exp", "--ttl-days", "1")
    run(board, "reopen", e1, "--reason", "migration killed wp3_reeval tmux")
    run(board, "message", e1, "--text",
        "resume from MLflow, do not re-run finished ckpts",
        "--audience", "exp")

    # a second worker session restarts and re-orients deterministically
    capsys.readouterr()
    run(board, "list")
    out = capsys.readouterr().out
    assert "counts:" in out

    capsys.readouterr()
    run(board, "pull", "--owner", "exp-b")
    out = capsys.readouterr().out
    assert f"claimed: {e1}" in out
    assert "gpu-ports: 32217/30318" in out
    assert "machine migrated" in out
    assert "resume from MLflow" in out
    # delegate's note ("how to check") is the surviving anchor across
    # submit -> reopen -> re-pull
    assert "anchor: tmux wp3_reeval @31431" in out

    # writeup node meanwhile: conductor re-prioritizes it behind the resume
    run(board, "priority", e2_declared, "5",
        "--reason", "data finalization waits")

    # round 2 finishes; supersede a stale follow-up; archive the subtree
    run(board, "submit", e1, "--owner", "exp-b", "--status", "done",
        "--output", "out/full.md:22/22 ckpts")
    stale = run_or_propose_followup(board, e1)
    fresh = propose_followup(board, e1, "fresh follow-up")
    run(board, "supersede", stale, fresh, "--reason", "stale draft")
    conn = db.connect(f"{board}/graph.db")
    assert conn.execute("SELECT state FROM nodes WHERE id=?",
                        (stale,)).fetchone()[0] == "canceled"
    conn.close()

    run(board, "pull", "--owner", "exp-c")
    run(board, "pull", "--owner", "exp-d")
    conn = db.connect(f"{board}/graph.db")
    open_exp = conn.execute(
        "SELECT id, owner FROM nodes WHERE type='experiment' AND "
        "state='active' ORDER BY created_at").fetchall()
    conn.close()
    for r in open_exp:
        run(board, "submit", r["id"], "--owner", r["owner"], "--status",
            "done", "--output", f"out/{r['id']}.md")

    # doctor is clean; archive everything terminal; live views go quiet
    run(board, "doctor")
    assert "doctor: healthy" in capsys.readouterr().out
    run(board, "archive", d1, "--under")
    capsys.readouterr()
    run(board, "query", "--state", "done")
    assert "no nodes match" in capsys.readouterr().out
    capsys.readouterr()
    run(board, "list", "--archived")
    assert d1 in capsys.readouterr().out


def propose_followup(board, parent, spec):
    run(board, "propose", "--type", "experiment", "--spec", spec,
        "--parent", parent)
    return node_by_type(board, "experiment", "proposed")


def run_or_propose_followup(board, parent):
    return propose_followup(board, parent, "stale follow-up draft")
