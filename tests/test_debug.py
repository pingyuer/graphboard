import asyncio
import json

import pytest

from graphboard import cli, core, db, scaffold


@pytest.fixture
def board(tmp_path):
    b = tmp_path / "proj" / ".board"
    scaffold.init_board(b, template="rd-classic")
    return b


def test_events_recorded_on_success(board):
    conn = db.connect(board / "graph.db")
    nid = core.propose(conn, "proposal", "p")
    core.approve(conn, nid)
    core.pull(conn, owner="prop-a")
    core.note(conn, nid, "working on it")
    core.submit(conn, nid, owner="prop-a", status="done",
                outputs=[{"path": "out/p.md"}])
    core.announce(conn, text="hello", owner="human")
    ev = core.events(conn)
    tools = [e["tool"] for e in ev]
    assert tools == ["propose", "approve", "pull", "note", "submit", "announce"]
    pull_ev = [e for e in ev if e["tool"] == "pull"][0]
    assert pull_ev["owner"] == "prop-a" and pull_ev["node_id"] == nid
    conn.close()


def test_events_recorded_on_failure(board):
    conn = db.connect(board / "graph.db")
    with pytest.raises(core.GbError):
        core.submit(conn, "n-nope", owner="x", status="done")
    nid = core.propose(conn, "proposal", "p")
    core.approve(conn, nid)
    core.pull(conn, owner="a")
    with pytest.raises(core.GbError):
        core.submit(conn, nid, owner="b", status="done",
                    outputs=[{"path": "o"}])
    ev = core.events(conn, tool="submit")
    assert len(ev) == 2
    assert all(e["detail"].startswith("error:") for e in ev)
    assert ev[1]["owner"] == "b"
    conn.close()


def test_events_filters(board):
    conn = db.connect(board / "graph.db")
    for i in range(3):
        core.propose(conn, "proposal", f"p{i}")
    assert len(core.events(conn, tool="propose")) == 3
    assert core.events(conn, tool="pull") == []
    assert len(core.events(conn, limit=2)) == 2
    conn.close()


def test_cli_log_and_filters(board, capsys):
    conn = db.connect(board / "graph.db")
    nid = core.propose(conn, "proposal", "p")
    core.approve(conn, nid)
    core.pull(conn, owner="prop-a")
    conn.close()
    b = str(board)
    assert cli.main(["--board", b, "log"]) == 0
    out = capsys.readouterr().out
    assert "propose" in out and "approve" in out and "pull [prop-a]" in out
    assert cli.main(["--board", b, "log", "--owner", "prop-a"]) == 0
    out = capsys.readouterr().out
    assert "pull" in out and "propose" not in out
    assert cli.main(["--board", b, "log", "--node", nid]) == 0
    out = capsys.readouterr().out
    assert nid in out


def test_cli_doctor_healthy(board, capsys):
    conn = db.connect(board / "graph.db")
    nid = core.propose(conn, "proposal", "p")
    core.approve(conn, nid)
    core.pull(conn, owner="prop-a")
    conn.close()
    assert cli.main(["--board", str(board), "doctor"]) == 0
    out = capsys.readouterr().out
    assert "doctor: healthy" in out
    assert "grammar OK" in out and "owner format OK" in out and "workdirs OK" in out


def test_cli_doctor_flags_issues(board, capsys):
    conn = db.connect(board / "graph.db")
    nid = core.propose(conn, "proposal", "p")
    core.approve(conn, nid)
    core.pull(conn, owner="Bad_Owner")
    conn.close()
    assert cli.main(["--board", str(board), "doctor"]) == 1
    out = capsys.readouterr().out
    assert "owner not in role-instance format" in out


def test_cli_doctor_flags_stale_proposed(board, capsys):
    conn = db.connect(board / "graph.db")
    nid = core.propose(conn, "proposal", "old")
    conn.execute("UPDATE nodes SET created_at='2020-01-01T00:00:00.000Z' "
                 "WHERE id=?", (nid,))
    conn.commit()
    conn.close()
    assert cli.main(["--board", str(board), "doctor",
                     "--stale-hours", "1"]) == 1
    assert "stale proposed" in capsys.readouterr().out


def test_cli_doctor_flags_phantom_claim(board, capsys):
    conn = db.connect(board / "graph.db")
    nid = core.propose(conn, "task", "t")
    core.approve(conn, nid)
    core.note(conn, nid, "claimed by impl-a; starting work")
    conn.close()
    assert cli.main(["--board", str(board), "doctor"]) == 1
    out = capsys.readouterr().out
    assert "claimed without pull" in out and nid in out


def test_cli_doctor_flags_swapped_grammar(tmp_path, capsys):
    proj = tmp_path / "proj"
    assert cli.main(["init", str(proj), "--template", "rd-classic"]) == 0
    grammar_path = proj / ".board" / "transitions.yaml"
    grammar_path.write_text(
        "default: approve\n"
        "transitions:\n"
        '  - {"from": done, "on": proposal, "to": implementation, '
        "activate: auto}\n")
    assert cli.main(["--board", str(proj / ".board"), "doctor"]) == 1
    assert "looks swapped" in capsys.readouterr().out


def test_cli_doctor_reports_chain_at_rest(board, capsys):
    assert cli.main(["--board", str(board), "doctor"]) == 0
    assert "chain at rest" in capsys.readouterr().out


def test_cli_doctor_flags_orphaned_blocked(board, capsys):
    conn = db.connect(board / "graph.db")
    parent = core.propose(conn, "plan", "p")
    core.approve(conn, parent)
    core.pull(conn, owner="arch-a")
    core.submit(conn, parent, owner="arch-a", status="blocked")
    child = core.propose(conn, "task", "c", parent=parent)
    core.reject(conn, child)
    conn.close()
    assert cli.main(["--board", str(board), "doctor"]) == 1
    out = capsys.readouterr().out
    assert "blocked parent with rejected child" in out


def test_cli_split_via_cli(tmp_path, capsys):
    proj = tmp_path / "proj"
    assert cli.main(["init", str(proj)]) == 0
    capsys.readouterr()
    b = str(proj / ".board")
    assert cli.main(["--board", b, "propose", "--type", "plan",
                     "--spec", "big"]) == 0
    out = capsys.readouterr().out
    plan = out.split()[1]
    assert cli.main(["--board", b, "approve", plan]) == 0
    assert cli.main(["--board", b, "pull", "--owner", "arch-a"]) == 0
    assert cli.main(["--board", b, "split", plan, "--owner", "arch-a",
                     "--child", "task|part one",
                     "--child", "task|part two"]) == 0
    out = capsys.readouterr().out
    assert "split -> blocked" in out and out.count("child: ") == 2


def test_server_log_written(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    monkeypatch.setenv("GB_BOARD", str(proj / ".board"))
    monkeypatch.setenv("GB_PROJECT", "mcp")
    monkeypatch.setenv("GB_REPO", str(tmp_path))
    monkeypatch.delenv("GB_DEBUG", raising=False)
    assert cli.main(["init", str(proj), "--name", "mcp"]) == 0
    import graphboard.server as srv
    srv._cache.clear()

    def call(tool, args):
        result = asyncio.run(srv.server.call_tool(tool, args))
        return result.content[0].text

    call("gb_propose", {"type": "proposal", "spec": "log me"})
    call("gb_submit", {"id": "n-nope", "owner": "x", "status": "done"})
    logfile = proj / ".board" / "server.log"
    assert logfile.exists()
    lines = [json.loads(l) for l in logfile.read_text().splitlines()]
    assert [l["tool"] for l in lines] == ["gb_propose", "gb_submit"]
    assert lines[0]["ok"] is True and lines[1]["ok"] is False
    assert "result" in lines[1] and "result" not in lines[0]
    assert "spec" in lines[0]["args"]


def test_server_log_verbose(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    monkeypatch.setenv("GB_BOARD", str(proj / ".board"))
    monkeypatch.setenv("GB_PROJECT", "mcp")
    monkeypatch.setenv("GB_REPO", str(tmp_path))
    monkeypatch.setenv("GB_DEBUG", "verbose")
    assert cli.main(["init", str(proj), "--name", "mcp"]) == 0
    import graphboard.server as srv
    srv._cache.clear()
    asyncio.run(srv.server.call_tool("gb_status", {}))
    line = json.loads((proj / ".board" / "server.log").read_text().splitlines()[-1])
    assert "result" in line and "args" in line


def test_server_log_disabled(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    monkeypatch.setenv("GB_BOARD", str(proj / ".board"))
    monkeypatch.setenv("GB_PROJECT", "mcp")
    monkeypatch.setenv("GB_REPO", str(tmp_path))
    monkeypatch.setenv("GB_DEBUG", "0")
    assert cli.main(["init", str(proj), "--name", "mcp"]) == 0
    import graphboard.server as srv
    srv._cache.clear()
    asyncio.run(srv.server.call_tool("gb_status", {}))
    assert not (proj / ".board" / "server.log").exists()
