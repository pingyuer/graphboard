import asyncio

import pytest

from graphboard import cli, db


@pytest.fixture
def env(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("GB_BOARD", str(proj / ".board"))
    monkeypatch.setenv("GB_PROJECT", "mcp")
    monkeypatch.setenv("GB_REPO", str(repo))
    assert cli.main(["init", str(proj), "--template", "rd-classic",
                     "--name", "mcp"]) == 0
    import graphboard.server as srv
    srv._cache.clear()
    return srv.server, proj / ".board", repo


def call(server, tool, args):
    result = asyncio.run(server.call_tool(tool, args))
    assert not result.is_error
    return result.content[0].text


def test_mcp_full_chain(env):
    server, board, _ = env

    out = call(server, "gb_propose",
               {"type": "proposal", "spec": "mcp smoke"})
    nid = out.split()[1]

    text = call(server, "gb_status", {})
    assert "proposed: 1" in text

    call(server, "gba_approve", {"id": nid})
    text = call(server, "gb_pull", {"owner": "p"})
    assert f"claimed: {nid}" in text
    assert "contract:" in text
    assert "workdir:" in text

    text = call(server, "gb_note", {"id": nid, "text": "drafting", "owner": "p"})
    assert "note updated" in text

    text = call(server, "gb_submit", {
        "id": nid, "owner": "p", "status": "done",
        "outputs": "out/p.md:v1",
        "successors": "implementation|build it"})
    assert "-> proposed [grammar approve]" in text

    conn = db.connect(board / "graph.db")
    impl = conn.execute(
        "SELECT id FROM nodes WHERE type='implementation'").fetchone()["id"]
    conn.close()

    call(server, "gba_approve", {"id": impl})
    text = call(server, "gb_pull", {"owner": "i", "type": "implementation"})
    assert f"claimed: {impl}" in text
    assert "out/p.md" in text

    text = call(server, "gb_submit", {
        "id": impl, "owner": "i", "status": "done",
        "outputs": "out/code.py",
        "successors": "acceptance|verify"})
    assert "-> pending [grammar auto]" in text

    call(server, "gb_pull", {"owner": "a"})
    text = call(server, "gba_announce", {"text": "freeze until Friday"})
    assert "announced" in text

    call(server, "gb_status", {})
    text = call(server, "gb_pull", {"owner": "a2"})
    assert "freeze until Friday" in text


def test_mcp_query(env):
    server, _, _ = env
    for i in range(3):
        out = call(server, "gb_propose", {"type": "proposal", "spec": f"p{i}"})
        call(server, "gba_approve", {"id": out.split()[1]})
    text = call(server, "gb_query", {"type": "proposal", "state": "pending"})
    assert text.count("(proposal, pending)") == 3
    text = call(server, "gb_query", {"owner": "nobody"})
    assert text == "no nodes match"


def test_mcp_gba_role(env):
    server, board, repo = env
    text = call(server, "gba_role", {
        "name": "perf-tuner",
        "description": "Tunes performance, benchmark driven.",
        "claims": "implementation",
        "duties": "Profile then optimize.",
    })
    assert "role registered" in text
    assert (repo / ".opencode" / "agents" / "perf-tuner.md").exists()
    content = (repo / ".opencode" / "agents" / "perf-tuner.md").read_text()
    assert "You are the perf-tuner role" in content
    assert "node types added" not in text
    text = call(server, "gba_role", {
        "name": "scout", "description": "Literature scouting.",
        "claims": "survey"})
    assert "node types added to nodetypes.yaml: survey" in text


def test_mcp_gba_role_requires_repo(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    monkeypatch.setenv("GB_BOARD", str(proj / ".board"))
    monkeypatch.setenv("GB_PROJECT", "mcp")
    monkeypatch.delenv("GB_REPO", raising=False)
    assert cli.main(["init", str(proj), "--name", "mcp"]) == 0
    import graphboard.server as srv
    srv._cache.clear()
    text = call(srv.server, "gba_role",
                {"name": "x", "description": "d", "claims": "task"})
    assert "GB_REPO" in text


def test_mcp_gba_grammar(env):
    server, _, _ = env
    text = call(server, "gba_grammar", {"action": "list"})
    assert "default: approve" in text
    assert "--done-->" in text

    text = call(server, "gba_grammar", {
        "action": "add", "frm": "proposal", "on": "done", "to": "docs",
        "activate": "approve"})
    assert "grammar updated" in text

    text = call(server, "gba_grammar", {"action": "list"})
    assert "--done--> docs" in text

    text = call(server, "gba_grammar", {
        "action": "add", "frm": "acceptance", "on": "explode", "to": "proposal"})
    assert "rejected by grammar-check" in text

    text = call(server, "gba_grammar", {
        "action": "add", "frm": "acceptance", "on": "fail",
        "to": "implementation", "activate": "auto"})
    assert "auto cycle" in text

    text = call(server, "gba_grammar", {
        "action": "remove", "frm": "proposal", "on": "done", "to": "docs"})
    assert "grammar updated" in text
    text = call(server, "gba_grammar", {"action": "list"})
    assert "--done--> docs" not in text


def test_mcp_gba_bootstrap(tmp_path, monkeypatch):
    board = tmp_path / "fresh" / ".board"
    monkeypatch.setenv("GB_BOARD", str(board))
    monkeypatch.delenv("GB_HOME", raising=False)
    monkeypatch.delenv("GB_PROJECT", raising=False)
    import graphboard.server as srv
    srv._cache.clear()
    text = call(srv.server, "gba_bootstrap", {"template": "minimal"})
    assert "bootstrapped board" in text
    assert (board / "graph.db").exists()
    text = call(srv.server, "gba_bootstrap", {})
    assert "already initialized" in text


def test_mcp_gba_grammar_aliases_and_swap_guard(env):
    server, _, _ = env
    text = call(server, "gba_grammar", {
        "action": "add", "from_type": "proposal", "event": "done",
        "to_type": "docs3", "activate": "approve"})
    assert "grammar updated: proposal --done--> docs3" in text
    text = call(server, "gba_grammar", {
        "action": "add", "frm": "done", "on": "proposal", "to": "implementation"})
    assert "looks swapped" in text
    text = call(server, "gba_grammar", {
        "action": "remove", "from_type": "proposal", "event": "done",
        "to_type": "docs3"})
    assert "grammar updated" in text


def test_mcp_pull_baseline(tmp_path, monkeypatch):
    import subprocess
    proj = tmp_path / "proj"
    monkeypatch.setenv("GB_BOARD", str(proj / ".board"))
    monkeypatch.setenv("GB_PROJECT", "mcp")
    monkeypatch.setenv("GB_REPO", str(proj))
    assert cli.main(["init", str(proj), "--name", "mcp", "--git"]) == 0
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "add", "."], cwd=proj, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-m", "init"], cwd=proj, check=True,
                   capture_output=True)
    import graphboard.server as srv
    srv._cache.clear()
    out = call(srv.server, "gb_propose", {"type": "proposal", "spec": "b"})
    call(srv.server, "gba_approve", {"id": out.split()[1]})
    text = call(srv.server, "gb_pull", {"owner": "p"})
    assert "baseline:" in text and "(clean)" in text


def test_mcp_split_roundtrip(env):
    server, board, _ = env
    out = call(server, "gb_propose", {"type": "plan", "spec": "big task"})
    plan = out.split()[1]
    call(server, "gba_approve", {"id": plan})
    assert "claimed" in call(server, "gb_pull", {"owner": "arch-a"})
    text = call(server, "gb_split", {
        "id": plan, "owner": "arch-a",
        "children": "task|part one;task|part two"})
    assert "split -> blocked" in text
    import re as _re
    kids = _re.findall(r"child: (\S+)", text)
    assert len(kids) == 2
    for k in kids:
        call(server, "gba_approve", {"id": k})

    def claim_and_submit():
        call(server, "gb_pull", {"owner": "w-x"})
        conn = db.connect(board / "graph.db")
        row = conn.execute(
            "SELECT id, owner FROM nodes WHERE type='task' AND state='active'"
        ).fetchone()
        conn.close()
        assert row is not None
        return call(server, "gb_submit", {"id": row["id"], "owner": row["owner"],
                                          "status": "done", "outputs": "out/x"})

    claim_and_submit()
    text = claim_and_submit()
    assert "reactivated parent" in text


def test_mcp_release_reattach_flow(env):
    server, board, _ = env
    out = call(server, "gb_propose", {"type": "task", "spec": "long work"})
    nid = out.split()[1]
    call(server, "gba_approve", {"id": nid})
    call(server, "gb_pull", {"owner": "w-a"})
    call(server, "gb_note", {"id": nid, "owner": "w-a",
                             "text": "tmux: n-x on srv1, 50% done"})
    text = call(server, "gba_release", {"id": nid, "reason": "session died"})
    assert "released" in text
    text = call(server, "gb_pull", {"owner": "w-b"})
    assert f"claimed: {nid}" in text and "tmux: n-x on srv1" in text
    text = call(server, "gb_submit", {"id": nid, "owner": "w-b",
                                      "status": "done", "outputs": "out/x"})
    assert "done" in text


def test_mcp_role_update(env):
    server, board, repo = env
    call(server, "gba_role", {"name": "scout2", "description": "v1.",
                              "claims": "survey"})
    text = call(server, "gba_role", {"name": "scout2", "description": "v2.",
                                     "claims": "survey,deepdive",
                                     "duties": "updated duties.",
                                     "action": "update"})
    assert "role updated" in text
    assert "node types added to nodetypes.yaml: deepdive" in text
    content = (repo / ".opencode" / "agents" / "scout2.md").read_text()
    assert "description: v2." in content and "updated duties." in content


def test_mcp_grammar_autodeclare(env):
    server, board, _ = env
    text = call(server, "gba_grammar", {"action": "add", "from_type": "mystery",
                                        "event": "done", "to_type": "enigma"})
    assert "auto-declared node type 'mystery'" in text
    assert "auto-declared node type 'enigma'" in text
    import yaml
    nt = yaml.safe_load((board / "nodetypes.yaml").read_text())
    assert nt["types"]["mystery"]["contract"].startswith("TODO")
    text = call(server, "gba_grammar", {"action": "add", "from_type": "enigma",
                                        "event": "done", "to_type": "mystery"})
    assert "grammar updated" in text and "unreachable" in text


def test_mcp_doctor_tool(env):
    server, board, _ = env
    text = call(server, "gb_doctor", {})
    assert "doctor: healthy" in text
    out = call(server, "gb_propose", {"type": "proposal", "spec": "s"})
    call(server, "gba_approve", {"id": out.split()[1]})
    call(server, "gb_pull", {"owner": "p"})
    call(server, "gb_note", {"id": out.split()[1], "owner": "p",
                             "text": "claimed by p without pull"})
    conn = db.connect(board / "graph.db")
    conn.execute("UPDATE nodes SET state='pending' WHERE type='proposal'")
    conn.commit()
    conn.close()
    text = call(server, "gb_doctor", {})
    assert "issue:" in text and "claimed without pull" in text


def test_mcp_tool_surface(env):
    import asyncio
    server, _, _ = env
    tools = asyncio.run(server.list_tools())
    names = sorted(t.name for t in tools)
    assert names == sorted([
        "gb_pull", "gb_submit", "gb_split", "gb_delegate", "gb_reactivate",
        "gb_propose", "gb_status", "gb_query", "gb_note", "gb_doctor",
        "gba_approve", "gba_release", "gba_cancel", "gba_hold", "gba_announce",
        "gba_priority", "gba_message", "gba_fact", "gba_reopen", "gba_archive",
        "gba_restore", "gba_supersede",
        "gba_bootstrap", "gba_role", "gba_grammar", "gba_export"])


def test_mcp_errors_are_textual(env):
    server, _, _ = env
    text = call(server, "gb_submit",
                {"id": "n-nope", "owner": "x", "status": "done"})
    assert text.startswith("error: node not found")
    text = call(server, "gba_approve", {"id": "n-nope"})
    assert text.startswith("error:")


def _claim(server, spec="s", ntype="proposal"):
    out = call(server, "gb_propose", {"type": ntype, "spec": spec})
    nid = out.split()[1]
    call(server, "gba_approve", {"id": nid})
    return nid


def test_mcp_priority_flow(env):
    server, _, _ = env
    a = _claim(server, "a"); b = _claim(server, "b")
    text = call(server, "gba_priority", {"id": b, "level": 1,
                                         "reason": "urgent"})
    assert "p1" in text
    text = call(server, "gb_pull", {"owner": "w"})
    assert f"claimed: {b}" in text and "[p1]" in text
    text = call(server, "gba_priority", {"id": a, "level": 99})
    assert text.startswith("error:")


def test_mcp_message_and_note_guard(env):
    server, _, _ = env
    nid = _claim(server)
    call(server, "gb_pull", {"owner": "impl-a"})
    call(server, "gb_note", {"id": nid, "owner": "impl-a", "text": "my anchor"})
    text = call(server, "gb_note", {"id": nid, "owner": "intruder-b",
                                    "text": "steal"})
    assert text.startswith("error:") and "owner-writable" in text
    call(server, "gba_message", {"id": nid, "text": "directive for impl",
                                 "audience": "impl"})
    call(server, "gba_message", {"id": nid, "text": "for reviewers only",
                                 "audience": "review"})
    text = call(server, "gb_status", {"id": nid})
    assert "my anchor" in text
    assert "directive for impl" in text and "for reviewers only" in text


def test_mcp_facts_injected_at_pull(env):
    server, _, _ = env
    call(server, "gba_fact", {"action": "set", "key": "gpu-ports",
                              "value": "32217/30318"})
    text = call(server, "gba_fact", {"action": "list"})
    assert "gpu-ports: 32217/30318" in text
    nid = _claim(server)
    text = call(server, "gb_pull", {"owner": "w"})
    assert f"claimed: {nid}" in text and "gpu-ports: 32217/30318" in text
    call(server, "gba_fact", {"action": "remove", "key": "gpu-ports"})
    text = call(server, "gba_fact", {"action": "list"})
    assert "no facts" in text


def test_mcp_announce_audience(env):
    server, _, _ = env
    call(server, "gba_announce", {"text": "impl-only notice",
                                  "audience": "impl"})
    _claim(server)
    text = call(server, "gb_pull", {"owner": "impl-a"})
    assert "impl-only notice" in text
    _claim(server)
    text = call(server, "gb_pull", {"owner": "review-a"})
    assert "impl-only notice" not in text


def test_mcp_status_owner_view(env):
    server, _, _ = env
    a = _claim(server, "a"); b = _claim(server, "b")
    call(server, "gb_pull", {"owner": "w-a"})
    call(server, "gb_pull", {"owner": "w-b"})
    call(server, "gb_delegate", {"id": b, "owner": "w-b",
                                 "resources": "gpu:srv1"})
    text = call(server, "gb_status", {"owner": "w-b"})
    assert "your nodes:" in text and b in text and "running" in text
    assert a not in text.split("your nodes:")[1].split("open nodes:")[0]


def test_mcp_repair_reopen_archive_supersede(env):
    server, board, _ = env
    nid = _claim(server)
    call(server, "gb_pull", {"owner": "w"})
    call(server, "gb_submit", {"id": nid, "owner": "w", "status": "done",
                               "outputs": "out/x"})
    text = call(server, "gba_reopen", {"id": nid, "reason": "world changed"})
    assert "reopened" in text and "pending" in text
    text = call(server, "gb_pull", {"owner": "w2"})
    assert f"claimed: {nid}" in text
    call(server, "gb_submit", {"id": nid, "owner": "w2", "status": "done",
                               "outputs": "out/y"})
    text = call(server, "gba_archive", {"id": nid})
    assert "archived" in text
    text = call(server, "gb_query", {"state": "done"})
    assert nid not in text
    text = call(server, "gba_export", {"include_archived": True})
    assert nid in text and "archived:" in text
    call(server, "gba_restore", {"id": nid})
    text = call(server, "gb_query", {"state": "done"})
    assert nid in text

    old = _claim(server, "old plan")
    new = call(server, "gb_propose",
               {"type": "proposal", "spec": "better plan"}).split()[1]
    text = call(server, "gba_supersede", {"old_id": old, "new_id": new,
                                          "reason": "improved"})
    assert "superseded" in text and "canceled" in text
    conn = db.connect(board / "graph.db")
    assert conn.execute("SELECT superseded_by FROM nodes WHERE id=?",
                        (old,)).fetchone()[0] == new
    assert conn.execute("SELECT state FROM nodes WHERE id=?",
                        (new,)).fetchone()[0] == "pending"
    conn.close()


def test_mcp_missing_board_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GB_BOARD", raising=False)
    monkeypatch.setenv("GB_HOME", str(tmp_path))
    monkeypatch.delenv("GB_PROJECT", raising=False)
    import graphboard.server as srv
    srv._cache.clear()
    text = call(srv.server, "gb_status", {})
    assert "GB_BOARD" in text or "GB_PROJECT" in text
