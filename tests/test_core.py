import threading

import pytest

from graphboard import core, db
from graphboard.grammar import Grammar, Rule


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "graph.db")
    yield c
    c.close()


@pytest.fixture
def grammar():
    return Grammar(default="approve", rules=[
        Rule("proposal", "done", "implementation", "approve"),
        Rule("implementation", "done", "acceptance", "auto"),
        Rule("acceptance", "fail", "implementation", "auto", budget=3),
    ])


def seed_pending(conn, ntype="task", spec="s"):
    nid = core.propose(conn, ntype, spec)
    core.approve(conn, nid)
    return nid


def test_pull_claim_race_exactly_one_winner(tmp_path):
    dbpath = tmp_path / "race.db"
    setup = db.connect(dbpath)
    seed_pending(setup, spec="contested")
    setup.close()

    results = []
    barrier = threading.Barrier(8)

    def worker(i):
        c = db.connect(dbpath)
        barrier.wait()
        try:
            r = core.pull(c, owner=f"w{i}")
            results.append(r)
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    winners = [r for r in results if r.get("claimed")]
    assert len(winners) == 1
    losers = [r for r in results if not r.get("claimed")]
    assert all(r["counts"]["active"] == 1 for r in losers)


def test_pull_returns_inputs_summary_announcements(conn, grammar):
    parent = seed_pending(conn, "proposal", "write it")
    core.pull(conn, owner="p1")
    core.submit(conn, parent, owner="p1", status="done",
                outputs=[{"path": "out/proposal.md", "note": "v1"}],
                successors=[{"type": "implementation", "spec": "build it"}],
                grammar=grammar)
    child = conn.execute(
        "SELECT id FROM nodes WHERE state='proposed'").fetchone()["id"]
    core.approve(conn, child)
    core.announce(conn, "always log seeds")
    r = core.pull(conn, owner="i1")
    assert r["claimed"]["type"] == "implementation"
    assert r["claimed"]["summary"] == "build it"
    # thin injection: no full spec, no contract, no facts dump
    assert "spec" not in r["claimed"]
    assert "contract" not in r and "facts" not in r
    assert r["inputs"][0]["path"] == "out/proposal.md"
    assert r["announcements"][0]["text"] == "always log seeds"
    r2 = core.pull(conn, owner="i1")
    assert r2["claimed"] is None


def test_announcement_delivered_once_per_owner(conn):
    seed_pending(conn)
    core.announce(conn, "hello")
    r1 = core.pull(conn, owner="a")
    assert len(r1["announcements"]) == 1
    seed_pending(conn)
    r2 = core.pull(conn, owner="a")
    assert r2["announcements"] == []
    seed_pending(conn)
    r3 = core.pull(conn, owner="b")
    assert len(r3["announcements"]) == 1


def test_submit_auto_successor_pending(conn, grammar):
    nid = seed_pending(conn, "implementation")
    core.pull(conn, owner="x")
    r = core.submit(conn, nid, owner="x", status="done",
                    outputs=[{"path": "out/code"}],
                    successors=[{"type": "acceptance", "spec": "verify"}],
                    grammar=grammar)
    assert r["successors"][0]["state"] == "pending"
    assert r["successors"][0]["reason"] == "grammar auto"


def test_submit_approve_successor_proposed(conn, grammar):
    nid = seed_pending(conn, "proposal")
    core.pull(conn, owner="x")
    r = core.submit(conn, nid, owner="x", status="done",
                    outputs=[{"path": "out/p.md"}],
                    successors=[{"type": "implementation", "spec": "build it"}],
                    grammar=grammar)
    assert r["successors"][0]["state"] == "proposed"
    assert r["successors"][0]["reason"] == "grammar approve"


def test_submit_default_policy_when_no_rule(conn):
    nid = seed_pending(conn, "mystery")
    core.pull(conn, owner="x")
    r = core.submit(conn, nid, owner="x", status="done",
                    outputs=[{"path": "out/x"}],
                    successors=[{"type": "other", "spec": "s"}],
                    grammar=Grammar(default="approve"))
    assert r["successors"][0]["state"] == "proposed"
    assert r["successors"][0]["reason"] == "default approve"


def test_submit_done_requires_outputs(conn, grammar):
    nid = seed_pending(conn)
    core.pull(conn, owner="x")
    with pytest.raises(core.GbError, match="requires at least one output"):
        core.submit(conn, nid, owner="x", status="done", grammar=grammar)


def test_submit_blocked_without_outputs_ok(conn, grammar):
    nid = seed_pending(conn)
    core.pull(conn, owner="x")
    r = core.submit(conn, nid, owner="x", status="blocked",
                    note="missing data", grammar=grammar)
    assert r["state"] == "blocked"


def test_submit_owner_mismatch_rejected(conn, grammar):
    nid = seed_pending(conn)
    core.pull(conn, owner="x")
    with pytest.raises(core.GbError, match="owned by"):
        core.submit(conn, nid, owner="y", status="done",
                    outputs=[{"path": "o"}], grammar=grammar)


def test_submit_inactive_node_rejected(conn, grammar):
    nid = seed_pending(conn)
    with pytest.raises(core.GbError, match="not active"):
        core.submit(conn, nid, owner="x", status="done",
                    outputs=[{"path": "o"}], grammar=grammar)


def test_budget_enforced_on_chain(tmp_path):
    c = db.connect(tmp_path / "b2.db")
    g = Grammar(rules=[
        Rule("impl", "done", "acc", "auto"),
        Rule("acc", "fail", "impl", "auto", budget=2),
    ])
    impl1 = core.propose(c, "impl", "v1")
    core.approve(c, impl1)
    core.pull(c, owner="w")
    core.submit(c, impl1, owner="w", status="done", outputs=[{"path": "o"}],
                successors=[{"type": "acc", "spec": "check v1"}], grammar=g)
    acc1 = c.execute("SELECT id FROM nodes WHERE type='acc'").fetchone()["id"]
    core.pull(c, owner="w")
    core.submit(c, acc1, owner="w", status="done", event="fail",
                outputs=[{"path": "o"}],
                successors=[{"type": "impl", "spec": "rework"}], grammar=g)
    impl2 = c.execute(
        "SELECT id, state FROM nodes WHERE type='impl' ORDER BY created_at DESC"
    ).fetchone()
    assert impl2["state"] == "pending"

    core.pull(c, owner="w")
    core.submit(c, impl2["id"], owner="w", status="done",
                outputs=[{"path": "o"}],
                successors=[{"type": "acc", "spec": "check v2"}], grammar=g)
    acc2 = c.execute(
        "SELECT id FROM nodes WHERE type='acc' ORDER BY created_at DESC"
    ).fetchone()["id"]
    core.pull(c, owner="w")
    core.submit(c, acc2, owner="w", status="done", event="fail",
                outputs=[{"path": "o"}],
                successors=[{"type": "impl", "spec": "rework again"}], grammar=g)
    impl3 = c.execute(
        "SELECT id, state FROM nodes WHERE type='impl' ORDER BY created_at DESC"
    ).fetchone()
    assert impl3["state"] == "proposed"
    c.close()


def test_query_filters_and_descendants(conn, grammar):
    plan = core.propose(conn, "plan", "the plan")
    core.approve(conn, plan)
    core.pull(conn, owner="arch")
    core.submit(conn, plan, owner="arch", status="done",
              outputs=[{"path": "out/plan.md"}],
              successors=[{"type": "impl", "spec": "a"},
                          {"type": "impl", "spec": "b"}],
              grammar=Grammar(rules=[Rule("plan", "done", "impl", "approve")]))
    impls = [r["id"] for r in conn.execute(
        "SELECT id FROM nodes WHERE type='impl' "
        "ORDER BY created_at, rowid").fetchall()]
    for i, owner in zip(impls, ("impl-a", "impl-b")):
        core.approve(conn, i)
        core.pull(conn, owner=owner)
        core.submit(conn, i, owner=owner, status="done",
                    outputs=[{"path": f"out/{i}.py"}])

    r = core.query(conn, type="impl", state="done")
    assert [n["id"] for n in r["nodes"]] == impls
    r = core.query(conn, under=plan)
    ids = {n["id"] for n in r["nodes"]}
    assert ids == set(impls) | {plan}
    r = core.query(conn, owner="impl-a")
    assert len(r["nodes"]) == 1 and r["nodes"][0]["outputs"][0]["path"].endswith(".py")
    r = core.query(conn, limit=1)
    assert r["truncated"] and len(r["nodes"]) == 1
    r = core.query(conn, under=impls[0])
    assert [n["id"] for n in r["nodes"]] == [impls[0]]


def test_query_under_rejects_unknown_node(conn):
    with pytest.raises(core.GbError, match="node not found"):
        core.query(conn, under="n-nope")


def test_pull_creates_workdir(conn):
    nid = seed_pending(conn, "task", "work")
    r = core.pull(conn, owner="w1")
    workdir = r["claimed"]["workdir"]
    assert workdir.endswith(f"nodes/{nid}/out")
    from pathlib import Path
    assert Path(workdir).is_dir()


def test_release_and_reattach(conn):
    nid = seed_pending(conn, "task", "long work")
    core.pull(conn, owner="w-a")
    core.note(conn, nid, "tmux session running, 50%")
    core.release(conn, nid, reason="session died")
    row = conn.execute("SELECT state, owner, note FROM nodes WHERE id=?",
                       (nid,)).fetchone()
    assert row["state"] == "pending" and row["owner"] is None
    assert row["note"] == "tmux session running, 50%"
    r = core.pull(conn, owner="w-b")
    assert r["claimed"]["id"] == nid
    core.submit(conn, nid, owner="w-b", status="done", outputs=[{"path": "o"}])


def test_release_validation(conn):
    nid = seed_pending(conn)
    with pytest.raises(core.GbError, match="only active\\|blocked"):
        core.release(conn, nid)
    core.pull(conn, owner="w-a")
    core.submit(conn, nid, owner="w-a", status="done", outputs=[{"path": "o"}])
    with pytest.raises(core.GbError, match="only active\\|blocked"):
        core.release(conn, nid)


def test_release_blocked_node(conn):
    nid = seed_pending(conn)
    core.pull(conn, owner="w-a")
    core.submit(conn, nid, owner="w-a", status="blocked", note="waiting")
    core.release(conn, nid, reason="unblocked by human")
    assert conn.execute("SELECT state FROM nodes WHERE id=?",
                        (nid,)).fetchone()["state"] == "pending"


def test_propose_with_parent_records_edge(conn):
    parent = core.propose(conn, "plan", "p")
    child = core.propose(conn, "task", "c", parent=parent)
    edge = conn.execute("SELECT from_id, on_event, to_id FROM edges").fetchone()
    assert (edge["from_id"], edge["on_event"], edge["to_id"]) == \
           (parent, "proposed", child)


def test_split_lifecycle_and_reactivation(conn):
    plan = core.propose(conn, "plan", "big task")
    core.approve(conn, plan)
    core.pull(conn, owner="arch-a")
    r = core.split(conn, plan, owner="arch-a", children=[
        {"type": "task", "spec": "part one"},
        {"type": "task", "spec": "part two"}])
    assert r["state"] == "blocked"
    assert [c["state"] for c in r["children"]] == ["proposed", "proposed"]
    node = conn.execute("SELECT state, owner FROM nodes WHERE id=?",
                        (plan,)).fetchone()
    assert node["state"] == "blocked" and node["owner"] is None

    kids = [c["id"] for c in r["children"]]
    core.approve(conn, kids[0])
    core.pull(conn, owner="w-a")
    core.submit(conn, kids[0], owner="w-a", status="done",
                outputs=[{"path": "out/a"}])
    assert conn.execute("SELECT state FROM nodes WHERE id=?",
                        (plan,)).fetchone()["state"] == "blocked"

    core.approve(conn, kids[1])
    core.pull(conn, owner="w-b")
    res = core.submit(conn, kids[1], owner="w-b", status="done",
                      outputs=[{"path": "out/b"}])
    assert res["reactivated"] == plan
    assert conn.execute("SELECT state FROM nodes WHERE id=?",
                        (plan,)).fetchone()["state"] == "pending"

    integ = core.pull(conn, owner="arch-a")
    assert integ["claimed"]["id"] == plan


def test_split_of_split_recursive(conn):
    plan = core.propose(conn, "plan", "big")
    core.approve(conn, plan)
    core.pull(conn, owner="arch-a")
    r1 = core.split(conn, plan, owner="arch-a",
                    children=[{"type": "task", "spec": "chunk"}])
    kid = r1["children"][0]["id"]
    core.approve(conn, kid)
    core.pull(conn, owner="w-a")
    r2 = core.split(conn, kid, owner="w-a",
                    children=[{"type": "task", "spec": "subchunk"}])
    grand = r2["children"][0]["id"]
    assert conn.execute("SELECT state FROM nodes WHERE id=?",
                        (kid,)).fetchone()["state"] == "blocked"
    core.approve(conn, grand)
    core.pull(conn, owner="w-b")
    res = core.submit(conn, grand, owner="w-b", status="done",
                      outputs=[{"path": "out/g"}])
    assert res["reactivated"] == kid
    assert conn.execute("SELECT state FROM nodes WHERE id=?",
                        (plan,)).fetchone()["state"] == "blocked"


def test_split_validation(conn):
    plan = core.propose(conn, "plan", "big")
    core.approve(conn, plan)
    core.pull(conn, owner="arch-a")
    with pytest.raises(core.GbError, match="at least one child"):
        core.split(conn, plan, owner="arch-a", children=[])
    with pytest.raises(core.GbError, match="owned by"):
        core.split(conn, plan, owner="somebody-else",
                   children=[{"type": "task", "spec": "x"}])
    other = core.propose(conn, "plan", "not active")
    with pytest.raises(core.GbError, match="only active"):
        core.split(conn, other, owner="arch-a",
                   children=[{"type": "task", "spec": "x"}])


def test_split_no_reactivation_with_foreign_sibling(conn):
    plan = core.propose(conn, "plan", "big")
    core.approve(conn, plan)
    core.pull(conn, owner="arch-a")
    r = core.split(conn, plan, owner="arch-a",
                   children=[{"type": "task", "spec": "part"}])
    kid = r["children"][0]["id"]
    foreign = core.propose(conn, "task", "foreign", parent=plan)
    core.approve(conn, foreign)
    core.pull(conn, owner="w-x")
    core.submit(conn, foreign, owner="w-x", status="done",
                outputs=[{"path": "out/f"}])
    assert conn.execute("SELECT state FROM nodes WHERE id=?",
                        (plan,)).fetchone()["state"] == "blocked"
    core.approve(conn, kid)
    core.pull(conn, owner="w-a")
    core.submit(conn, kid, owner="w-a", status="done",
                outputs=[{"path": "out/k"}])
    assert conn.execute("SELECT state FROM nodes WHERE id=?",
                        (plan,)).fetchone()["state"] == "blocked"


def test_submit_done_error_teaches_fallback(conn):
    nid = seed_pending(conn)
    core.pull(conn, owner="x")
    core.submit(conn, nid, owner="x", status="done", outputs=[{"path": "o"}])
    with pytest.raises(core.GbError, match="use propose"):
        core.submit(conn, nid, owner="x", status="done", outputs=[{"path": "o"}])


def test_parse_shared_helpers():
    assert core.parse_outputs(["a.md:note", "b.md"]) == [
        {"path": "a.md", "note": "note"}, {"path": "b.md", "note": None}]
    assert core.parse_outputs([]) == []
    assert core.parse_successors(["t|do it;and keep the ; inside",
                                  "u|and this"]) == [
        {"type": "t", "spec": "do it;and keep the ; inside"},
        {"type": "u", "spec": "and this"}]
    with pytest.raises(core.GbError, match="TYPE\\|SPEC"):
        core.parse_successors(["broken"])
    with pytest.raises(core.GbError, match="PATH"):
        core.parse_outputs([":no-path"])
    with pytest.raises(core.GbError, match="not a ';'-joined"):
        core.parse_successors("t|do it;u|and this")
    with pytest.raises(core.GbError, match="not a ';'-joined"):
        core.parse_outputs("a.md;b.md")


def test_pull_reports_awaiting_approval(conn):
    core.propose(conn, "task", "t1")
    core.propose(conn, "task", "t2")
    r = core.pull(conn, owner="w")
    assert r["claimed"] is None and r["awaiting_approval"] == 2
    r = core.pull(conn, owner="w", type_filter="other")
    assert r["awaiting_approval"] == 0


def test_submit_flags_default_fallback(conn):
    g = Grammar(rules=[Rule("mystery", "done", "x", "auto")])
    nid = seed_pending(conn, "mystery")
    core.pull(conn, owner="x")
    r = core.submit(conn, nid, owner="x", status="done",
                    outputs=[{"path": "o"}],
                    successors=[{"type": "next", "spec": "s"}], grammar=g)
    assert "no rule matched" in r["successors"][0]["reason"]


def test_note_replaces(conn):
    nid = seed_pending(conn)
    core.note(conn, nid, "first")
    core.note(conn, nid, "second")
    row = conn.execute("SELECT note FROM nodes WHERE id=?", (nid,)).fetchone()
    assert row["note"] == "second"


def test_approve_reject_lifecycle(conn):
    nid = core.propose(conn, "t", "s")
    core.reject(conn, nid)
    assert conn.execute("SELECT state FROM nodes WHERE id=?",
                        (nid,)).fetchone()["state"] == "rejected"
    nid2 = core.propose(conn, "t", "s")
    core.approve(conn, nid2, spec_edit="refined")
    row = conn.execute("SELECT state, spec FROM nodes WHERE id=?",
                       (nid2,)).fetchone()
    assert row["state"] == "pending" and row["spec"] == "refined"
    with pytest.raises(core.GbError):
        core.approve(conn, nid2)


def test_announce_clear(conn):
    core.announce(conn, "old")
    core.announce(conn, "new", clear=True)
    rows = conn.execute(
        "SELECT text, active FROM announcements ORDER BY id").fetchall()
    assert rows[0]["active"] == 0 and rows[1]["active"] == 1


def test_batch_successors_pulled_in_declaration_order(conn):
    plan = core.propose(conn, "plan", "p")
    core.approve(conn, plan)
    core.pull(conn, owner="arch")
    core.submit(conn, plan, owner="arch", status="done",
                outputs=[{"path": "out/plan.md"}],
                successors=[{"type": "task", "spec": "first"},
                            {"type": "task", "spec": "second"},
                            {"type": "task", "spec": "third"}])
    kids = [n["id"] for n in core.query(conn, type="task")["nodes"]]
    for k in kids:
        core.approve(conn, k)
    specs = []
    for i in ("w1", "w2", "w3"):
        r = core.pull(conn, owner=i)
        specs.append(r["claimed"]["summary"])
    assert specs == ["first", "second", "third"]


def test_cancel_lifecycle(conn):
    nid = core.propose(conn, "task", "t")
    core.cancel(conn, nid, reason="superseded")
    assert conn.execute("SELECT state FROM nodes WHERE id=?",
                        (nid,)).fetchone()["state"] == "canceled"
    with pytest.raises(core.GbError, match="already canceled"):
        core.cancel(conn, nid)
    assert core.pull(conn, owner="w")["claimed"] is None


def test_cancel_active_running_blocked(conn):
    a = core.propose(conn, "task", "a")
    core.approve(conn, a)
    core.pull(conn, owner="w")
    core.cancel(conn, a, reason="abandoned")
    assert conn.execute("SELECT state FROM nodes WHERE id=?",
                        (a,)).fetchone()["state"] == "canceled"
    b = core.propose(conn, "task", "b")
    core.approve(conn, b)
    core.pull(conn, owner="w")
    core.delegate(conn, b, owner="w", resources="gpu:srv1")
    core.cancel(conn, b, reason="machine died")
    row = conn.execute("SELECT state, resources FROM nodes WHERE id=?",
                       (b,)).fetchone()
    assert row["state"] == "canceled" and row["resources"] is None


def test_hold_and_release_cycle(conn):
    nid = core.propose(conn, "task", "t")
    core.approve(conn, nid)
    core.hold(conn, nid, reason="human postponed")
    assert conn.execute("SELECT state FROM nodes WHERE id=?",
                        (nid,)).fetchone()["state"] == "blocked"
    assert core.pull(conn, owner="w")["claimed"] is None
    core.release(conn, nid)
    r = core.pull(conn, owner="w")
    assert r["claimed"]["id"] == nid
    with pytest.raises(core.GbError, match="only proposed\\|pending"):
        core.hold(conn, nid)


def test_delegate_harvest_reactivate_cycle(conn):
    nid = core.propose(conn, "task", "long work")
    core.approve(conn, nid)
    core.pull(conn, owner="exp-a")
    r = core.delegate(conn, nid, owner="exp-a", resources="gpu:srv1;machine:srv2",
                      note="tmux: n-x on srv1", check_after="2099-01-01T00:00:00Z")
    assert r["state"] == "running"
    row = conn.execute("SELECT state, owner, resources, check_after FROM nodes "
                       "WHERE id=?", (nid,)).fetchone()
    assert row["state"] == "running" and row["owner"] == "exp-a"
    assert row["resources"] == "gpu:srv1;machine:srv2"
    with pytest.raises(core.GbError, match="owned by"):
        core.submit(conn, nid, owner="exp-b", status="done",
                    outputs=[{"path": "o"}])
    r = core.query(conn, state="running")
    assert r["nodes"][0]["resources"] == "gpu:srv1;machine:srv2"
    core.reactivate(conn, nid, owner="exp-a")
    assert conn.execute("SELECT state FROM nodes WHERE id=?",
                        (nid,)).fetchone()["state"] == "active"
    core.delegate(conn, nid, owner="exp-a")
    core.submit(conn, nid, owner="exp-a", status="done",
                outputs=[{"path": "out/results.md"}])
    row = conn.execute("SELECT state, resources, check_after FROM nodes "
                       "WHERE id=?", (nid,)).fetchone()
    assert row["state"] == "done" and row["resources"] is None \
        and row["check_after"] is None


def test_delegate_validation(conn):
    nid = core.propose(conn, "task", "t")
    with pytest.raises(core.GbError, match="only active"):
        core.delegate(conn, nid, owner="w")
    core.approve(conn, nid)
    core.pull(conn, owner="w-a")
    with pytest.raises(core.GbError, match="owned by"):
        core.delegate(conn, nid, owner="w-b")


def test_reactivate_validation(conn):
    nid = core.propose(conn, "task", "t")
    core.approve(conn, nid)
    core.pull(conn, owner="w")
    with pytest.raises(core.GbError, match="only running"):
        core.reactivate(conn, nid, owner="w")


def test_announcement_ttl(conn):
    core.announce(conn, text="expires soon", ttl_days=-1)
    core.announce(conn, text="still valid", ttl_days=7)
    core.announce(conn, text="no expiry")
    nid = core.propose(conn, "task", "t")
    core.approve(conn, nid)
    r = core.pull(conn, owner="w")
    texts = [a["text"] for a in r["announcements"]]
    assert "expires soon" not in texts
    assert "still valid" in texts and "no expiry" in texts


def test_submit_undeclared_auto_notice(conn):
    g = Grammar(rules=[Rule("task", "done", "review", "auto")])
    nid = core.propose(conn, "task", "t")
    core.approve(conn, nid)
    core.pull(conn, owner="w")
    r = core.submit(conn, nid, owner="w", status="done",
                    outputs=[{"path": "o"}], grammar=g)
    assert any("task --done--> review" in n for n in r["notices"])
    n2 = core.propose(conn, "task", "t2")
    core.approve(conn, n2)
    core.pull(conn, owner="w")
    r = core.submit(conn, n2, owner="w", status="done",
                    outputs=[{"path": "o"}],
                    successors=[{"type": "review", "spec": "check it"}],
                    grammar=g)
    assert r["notices"] == []


def test_migration_from_old_schema(tmp_path):
    import sqlite3
    dbpath = tmp_path / "old.db"
    old = sqlite3.connect(dbpath)
    old.executescript("""
    CREATE TABLE nodes(
      id TEXT PRIMARY KEY, type TEXT NOT NULL,
      state TEXT NOT NULL CHECK(state IN ('proposed','pending','active',
                                          'done','blocked','rejected')),
      parent TEXT, on_event TEXT, owner TEXT, spec TEXT NOT NULL, note TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE announcements(id INTEGER PRIMARY KEY AUTOINCREMENT,
      text TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL);
    INSERT INTO nodes VALUES('n-old','task','done',NULL,NULL,'w','spec',
      'note','2020-01-01T00:00:00.000Z','2020-01-01T00:00:00.000Z');
    INSERT INTO announcements(text, active, created_at)
      VALUES('hello', 1, '2020-01-01T00:00:00.000Z');
    """)
    old.commit()
    old.close()
    from graphboard import db
    conn = db.connect(dbpath)
    row = conn.execute("SELECT * FROM nodes WHERE id='n-old'").fetchone()
    assert row["state"] == "done" and row["spec"] == "spec"
    assert row["resources"] is None and row["check_after"] is None
    assert row["priority"] == core.PRIORITY_DEFAULT
    assert row["archived"] == 0 and row["superseded_by"] is None
    ann_cols = {r["name"] for r in conn.execute("PRAGMA table_info(announcements)")}
    assert {"expires_at", "audience"} <= ann_cols
    for table in ("messages", "message_reads", "facts"):
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)).fetchone() is not None
    n = core.propose(conn, "task", "new era")
    core.approve(conn, n)
    core.pull(conn, owner="w")
    core.delegate(conn, n, owner="w", resources="gpu:x")
    core.cancel(conn, n, reason="test")
    assert conn.execute("SELECT state FROM nodes WHERE id=?",
                        (n,)).fetchone()["state"] == "canceled"
    conn.close()
    conn2 = db.connect(dbpath)
    assert conn2.execute("SELECT COUNT(*) c FROM nodes").fetchone()["c"] == 2
    conn2.close()


# --- scheduling plane: priority ---

def test_priority_default_and_propose(conn):
    nid = core.propose(conn, "task", "normal")
    assert conn.execute("SELECT priority FROM nodes WHERE id=?",
                        (nid,)).fetchone()[0] == 3
    hot = core.propose(conn, "task", "urgent", priority=1)
    assert conn.execute("SELECT priority FROM nodes WHERE id=?",
                        (hot,)).fetchone()[0] == 1
    with pytest.raises(core.GbError):
        core.propose(conn, "task", "bad", priority=0)
    with pytest.raises(core.GbError):
        core.propose(conn, "task", "bad", priority=10)


def test_priority_pull_serves_lower_first(conn):
    a = core.propose(conn, "task", "a"); core.approve(conn, a)
    b = core.propose(conn, "task", "b"); core.approve(conn, b)
    c = core.propose(conn, "task", "c"); core.approve(conn, c)
    core.set_priority(conn, c, 1)
    got = core.pull(conn, owner="w")["claimed"]["id"]
    assert got == c
    got2 = core.pull(conn, owner="w2")["claimed"]["id"]
    assert got2 == a


def test_priority_inherited_by_successors(conn, grammar):
    nid = core.propose(conn, "proposal", "urgent root", priority=1)
    core.approve(conn, nid)
    core.pull(conn, owner="w")
    core.note(conn, nid, "x", owner="w")
    r = core.submit(conn, nid, owner="w", status="done",
                    outputs=[{"path": "out/p"}],
                    successors=[{"type": "implementation", "spec": "s"}],
                    grammar=grammar)
    child = r["successors"][0]["id"]
    assert conn.execute("SELECT priority FROM nodes WHERE id=?",
                        (child,)).fetchone()[0] == 1


def test_priority_inherited_by_split(conn):
    nid = core.propose(conn, "task", "big urgent", priority=2)
    core.approve(conn, nid)
    core.pull(conn, owner="w")
    r = core.split(conn, nid, owner="w",
                   children=[{"type": "task", "spec": "c1"},
                             {"type": "task", "spec": "c2"}])
    for c in r["children"]:
        assert conn.execute("SELECT priority FROM nodes WHERE id=?",
                            (c["id"],)).fetchone()[0] == 2


def test_set_priority_validation(conn):
    nid = core.propose(conn, "task", "s")
    core.approve(conn, nid)
    core.pull(conn, owner="w")
    with pytest.raises(core.GbError):
        core.set_priority(conn, nid, 5)
    with pytest.raises(core.GbError):
        core.set_priority(conn, nid, 0)
    core.submit(conn, nid, owner="w", status="done", outputs=[{"path": "o"}])
    with pytest.raises(core.GbError):
        core.set_priority(conn, nid, 5)


def test_set_priority_survives_hold_release(conn):
    nid = core.propose(conn, "task", "s")
    core.approve(conn, nid)
    core.hold(conn, nid, reason="park")
    core.set_priority(conn, nid, 1)
    core.release(conn, nid)
    assert conn.execute("SELECT priority FROM nodes WHERE id=?",
                        (nid,)).fetchone()[0] == 1


# --- injection plane: audience, messages, facts, status self-view ---

def test_audience_match():
    assert core.audience_match("*", "impl-a")
    assert core.audience_match(None, "impl-a")
    assert core.audience_match("impl", "impl-a")
    assert core.audience_match("impl-a", "impl-a")
    assert not core.audience_match("review", "impl-a")
    assert not core.audience_match("impl-b", "impl-a")
    assert core.role_of("impl-a") == "impl"
    assert core.role_of("solo") == "solo"


def test_announce_audience_delivered_only_to_match(conn):
    core.announce(conn, text="gpu ports changed", audience="experimenter")
    r_exp = core.pull(conn, owner="experimenter-a")
    assert any("gpu ports" in a["text"] for a in r_exp["announcements"])
    r_des = core.pull(conn, owner="designer-a")
    assert r_des["announcements"] == []
    conn.execute("INSERT INTO nodes(id,type,state,spec,created_at,updated_at,"
                 "priority,archived) VALUES('n-x','task','pending','s',"
                 "'2020-01-01','2020-01-01',3,0)")
    conn.commit()
    r_des2 = core.pull(conn, owner="designer-a")
    assert r_des2["claimed"]["id"] == "n-x"
    assert r_des2["announcements"] == []


def test_message_delivered_at_pull_with_anchor_intact(conn):
    nid = core.propose(conn, "task", "s")
    core.approve(conn, nid)
    core.pull(conn, owner="w-a")
    core.note(conn, nid, "anchor by w-a", owner="w-a")
    core.message(conn, nid, author="conductor", text="hold your horses",
                 audience="*")
    core.submit(conn, nid, owner="w-a", status="blocked")
    core.release(conn, nid)
    r = core.pull(conn, owner="w-b")
    assert r["claimed"]["id"] == nid
    assert r["claimed"]["note"] == "anchor by w-a"
    assert any("hold your horses" in m["text"] for m in r["messages"])
    reads = conn.execute("SELECT COUNT(*) c FROM message_reads WHERE "
                         "recipient='w-b'").fetchone()["c"]
    assert reads == 1


def test_message_audience_filtering(conn):
    nid = core.propose(conn, "task", "s")
    core.approve(conn, nid)
    core.message(conn, nid, author="conductor", text="only for impl",
                 audience="impl")
    core.message(conn, nid, author="conductor", text="for everyone")
    r = core.pull(conn, owner="impl-a")
    texts = [m["text"] for m in r["messages"]]
    assert "only for impl" in texts and "for everyone" in texts
    assert r["claimed"]["id"] == nid


def test_note_owner_enforced(conn):
    nid = core.propose(conn, "task", "s")
    core.approve(conn, nid)
    core.pull(conn, owner="w-a")
    core.note(conn, nid, "mine", owner="w-a")
    with pytest.raises(core.GbError):
        core.note(conn, nid, "intruder", owner="w-b")
    core.note(conn, nid, "human override")
    assert conn.execute("SELECT note FROM nodes WHERE id=?",
                        (nid,)).fetchone()[0] == "human override"


def test_facts_set_list_remove_query_only(conn):
    core.fact_set(conn, "gpu-servers", "32217/30318", by="gb")
    core.fact_set(conn, "mlflow", "http://172.16.240.77:5000", by="gb")
    rows = core.facts(conn)
    assert [f["key"] for f in rows] == ["gpu-servers", "mlflow"]
    core.fact_set(conn, "gpu-servers", "changed", by="gb")
    assert core.facts(conn)[0]["value"] == "changed"
    with pytest.raises(core.GbError):
        core.fact_set(conn, "bad key!", "v")
    with pytest.raises(core.GbError):
        core.fact_set(conn, "k", " ")
    nid = core.propose(conn, "task", "s")
    core.approve(conn, nid)
    r = core.pull(conn, owner="w")
    # facts are query-only now; they are NOT injected at pull
    assert "facts" not in r
    assert any(f["key"] == "gpu-servers" for f in core.facts(conn))
    core.fact_remove(conn, "mlflow", by="gb")
    with pytest.raises(core.GbError):
        core.fact_remove(conn, "nope")


def test_status_owner_self_view(conn):
    a = core.propose(conn, "task", "a"); core.approve(conn, a)
    b = core.propose(conn, "task", "b"); core.approve(conn, b)
    core.pull(conn, owner="w-a")
    core.pull(conn, owner="w-b")
    core.delegate(conn, b, owner="w-b", resources="gpu:x")
    s = core.status(conn, owner="w-b")
    assert [n["id"] for n in s["yours"]] == [b]
    assert s["yours"][0]["state"] == "running"
    s2 = core.status(conn, owner="nobody")
    assert s2["yours"] == []
    assert "counts" in s and "yours" in s and "open" in s


# --- repair plane: reopen, archive/restore, supersede ---

def _done_node(conn, spec="s"):
    nid = core.propose(conn, "task", spec)
    core.approve(conn, nid)
    core.pull(conn, owner="w")
    core.submit(conn, nid, owner="w", status="done",
                outputs=[{"path": "out/x"}], note="final anchor")
    return nid


def test_reopen_done_back_to_pending(conn):
    nid = _done_node(conn)
    core.reopen(conn, nid, reason="world changed")
    row = conn.execute("SELECT * FROM nodes WHERE id=?", (nid,)).fetchone()
    assert row["state"] == "pending" and row["owner"] is None
    assert row["note"] == "final anchor"
    ev = conn.execute("SELECT detail FROM events WHERE tool='reopen'"
                      ).fetchone()[0]
    assert "done -> pending" in ev and "world changed" in ev


def test_reopen_rejects_live_nodes(conn):
    nid = core.propose(conn, "task", "s")
    core.approve(conn, nid)
    core.pull(conn, owner="w")
    with pytest.raises(core.GbError):
        core.reopen(conn, nid)


def test_reopen_unarchives(conn):
    nid = _done_node(conn)
    core.archive(conn, nid)
    core.reopen(conn, nid, reason="resume")
    row = conn.execute("SELECT state, archived FROM nodes WHERE id=?",
                       (nid,)).fetchone()
    assert row["state"] == "pending" and row["archived"] == 0


def test_archive_terminal_only_and_atomic_subtree(conn, grammar):
    nid = core.propose(conn, "proposal", "root")
    core.approve(conn, nid)
    core.pull(conn, owner="w")
    r = core.submit(conn, nid, owner="w", status="done",
                    outputs=[{"path": "o"}],
                    successors=[{"type": "implementation", "spec": "child"}],
                    grammar=grammar)
    child = r["successors"][0]["id"]
    with pytest.raises(core.GbError):
        core.archive(conn, nid, under=True)
    core.approve(conn, child)
    core.pull(conn, owner="w2")
    core.submit(conn, child, owner="w2", status="done",
                outputs=[{"path": "o2"}])
    count = core.archive(conn, nid, under=True)
    assert count == 2
    assert conn.execute("SELECT archived FROM nodes WHERE id=?",
                        (child,)).fetchone()[0] == 1


def test_archived_hidden_from_live_views(conn):
    nid = _done_node(conn)
    core.archive(conn, nid)
    assert core.query(conn, state="done")["nodes"] == []
    assert core.query(conn, state="done",
                      include_archived=True)["nodes"][0]["id"] == nid
    assert nid not in [n["id"] for n in core.status(conn)["open"]]
    assert core.status(conn)["counts"]["archived"] == 1
    core.restore(conn, nid)
    assert core.query(conn, state="done")["nodes"][0]["id"] == nid
    with pytest.raises(core.GbError):
        core.restore(conn, nid)


def test_supersede_atomic(conn):
    old = core.propose(conn, "task", "old plan")
    core.approve(conn, old)
    new = core.propose(conn, "task", "improved plan")
    r = core.supersede(conn, old, new, reason="better idea")
    assert r == {"old": old, "new": new, "approved": True}
    old_row = conn.execute("SELECT * FROM nodes WHERE id=?",
                           (old,)).fetchone()
    new_row = conn.execute("SELECT * FROM nodes WHERE id=?",
                           (new,)).fetchone()
    assert old_row["state"] == "canceled" and old_row["superseded_by"] == new
    assert new_row["state"] == "pending"
    evs = conn.execute("SELECT node_id, detail FROM events "
                       "WHERE tool='supersede' ORDER BY id").fetchall()
    assert len(evs) == 2 and evs[0]["node_id"] == old


def test_supersede_validation(conn):
    old = core.propose(conn, "task", "old")
    core.approve(conn, old)
    core.pull(conn, owner="w")
    new = core.propose(conn, "task", "new")
    with pytest.raises(core.GbError):
        core.supersede(conn, old, new)
    core.submit(conn, old, owner="w", status="done", outputs=[{"path": "o"}])
    with pytest.raises(core.GbError):
        core.supersede(conn, old, new)
    pending_new = core.propose(conn, "task", "pn")
    core.approve(conn, pending_new)
    other = core.propose(conn, "task", "o2")
    core.approve(conn, other)
    r = core.supersede(conn, other, pending_new)
    assert r["approved"] is False


# --- node as a first-class citizen: summary, charter, self-release, lossless audit ---

def test_summary_explicit_and_fallback(conn):
    nid = core.propose(conn, "task", "line one\nline two", summary="hand written")
    assert conn.execute("SELECT summary FROM nodes WHERE id=?",
                        (nid,)).fetchone()[0] == "hand written"
    auto = core.propose(conn, "task", "first line is the summary\nrest")
    assert conn.execute("SELECT summary FROM nodes WHERE id=?",
                        (auto,)).fetchone()[0] == "first line is the summary"
    long_spec = "x" * 400
    trunc = core.propose(conn, "task", long_spec)
    summ = conn.execute("SELECT summary FROM nodes WHERE id=?",
                        (trunc,)).fetchone()[0]
    assert summ.endswith("…") and len(summ) <= core.SUMMARY_MAX + 1


def test_summary_of_successors_and_split(conn):
    plan = core.propose(conn, "plan", "p")
    core.approve(conn, plan)
    core.pull(conn, owner="arch")
    r = core.submit(conn, plan, owner="arch", status="done",
                    outputs=[{"path": "o"}],
                    successors=[{"type": "task", "spec": "child summary\nbody"}])
    kid = r["successors"][0]["id"]
    assert conn.execute("SELECT summary FROM nodes WHERE id=?",
                        (kid,)).fetchone()[0] == "child summary"


def test_set_summary_validation(conn):
    nid = core.propose(conn, "task", "s")
    core.set_summary(conn, nid, "repaired")
    assert conn.execute("SELECT summary FROM nodes WHERE id=?",
                        (nid,)).fetchone()[0] == "repaired"
    with pytest.raises(core.GbError):
        core.set_summary(conn, nid, "   ")
    with pytest.raises(core.GbError):
        core.set_summary(conn, nid, "y" * (core.SUMMARY_MAX * 2 + 10))


def test_charter_roundtrip(conn):
    assert core.charter_get(conn) == ""
    core.charter_set(conn, "We reproduce paper X.\nFocus: Tab.1.")
    assert core.charter_get(conn) == "We reproduce paper X.\nFocus: Tab.1."
    with pytest.raises(core.GbError):
        core.charter_set(conn, "   ")


def test_unclaim_self_release(conn):
    nid = core.propose(conn, "task", "s")
    core.approve(conn, nid)
    core.pull(conn, owner="w-a")
    core.note(conn, nid, "my anchor", owner="w-a")
    core.unclaim(conn, nid, owner="w-a", reason="dependency not ready")
    row = conn.execute("SELECT * FROM nodes WHERE id=?", (nid,)).fetchone()
    assert row["state"] == "pending" and row["owner"] is None
    assert row["note"] == "my anchor"
    with pytest.raises(core.GbError):
        core.unclaim(conn, nid, owner="w-a")
    core.pull(conn, owner="w-b")
    with pytest.raises(core.GbError):
        core.unclaim(conn, nid, owner="w-a")


def test_audit_detail_lossless(conn):
    long_text = "z" * 500
    nid = core.propose(conn, "task", "s")
    core.approve(conn, nid)
    core.pull(conn, owner="w")
    core.note(conn, nid, long_text, owner="w")
    ev = [e for e in core.events(conn, node_id=nid) if e["tool"] == "note"]
    assert len(ev) == 1 and len(ev[0]["detail"]) == 500


def test_msg_count_attached_to_query_and_status(conn):
    nid = core.propose(conn, "task", "s")
    core.approve(conn, nid)
    core.message(conn, nid, author="conductor", text="heads up")
    q = core.query(conn, state="pending")["nodes"]
    assert q[0]["msg_count"] == 1
    s = core.status(conn)["open"]
    assert [n for n in s if n["id"] == nid][0]["msg_count"] == 1


def test_status_delivery_marks_read_filters_audience(conn):
    nid = core.propose(conn, "task", "s")
    core.approve(conn, nid)
    core.message(conn, nid, author="conductor", text="for impl",
                 audience="impl")
    core.message(conn, nid, author="conductor", text="for all")
    s = core.status(conn, nid)
    assert len(s["messages"]) == 2
    assert conn.execute("SELECT COUNT(*) c FROM message_reads"
                        ).fetchone()["c"] == 0
    s2 = core.status(conn, nid, owner="impl-a")
    texts = [m["text"] for m in s2["messages"]]
    assert "for impl" in texts and "for all" in texts
    assert conn.execute("SELECT COUNT(*) c FROM message_reads WHERE "
                        "recipient='impl-a'").fetchone()["c"] == 2
    s3 = core.status(conn, nid, owner="impl-a")
    assert s3["messages"] == []
