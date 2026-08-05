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


def test_pull_returns_inputs_contract_announcements(conn, grammar):
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
    contracts = {"implementation": {"contract": "follow the proposal"}}
    r = core.pull(conn, owner="i1", contracts=contracts)
    assert r["claimed"]["type"] == "implementation"
    assert r["inputs"][0]["path"] == "out/proposal.md"
    assert r["contract"] == "follow the proposal"
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
        "ORDER BY created_at, id").fetchall()]
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
    assert core.parse_outputs("a.md:note;b.md") == [
        {"path": "a.md", "note": "note"}, {"path": "b.md", "note": None}]
    assert core.parse_outputs(["a.md:note", "b.md"]) == [
        {"path": "a.md", "note": "note"}, {"path": "b.md", "note": None}]
    assert core.parse_outputs("") == []
    assert core.parse_successors("t|do it;u|and this") == [
        {"type": "t", "spec": "do it"}, {"type": "u", "spec": "and this"}]
    with pytest.raises(core.GbError, match="TYPE\\|SPEC"):
        core.parse_successors("broken")
    with pytest.raises(core.GbError, match="PATH"):
        core.parse_outputs(":no-path")


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
