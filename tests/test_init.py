import json
import subprocess

from graphboard import cli


def test_init_scaffolds_self_contained_workspace(tmp_path, capsys):
    proj = tmp_path / "myproj"
    code = cli.main(["init", str(proj), "--name", "myproj"])
    assert code == 0

    board = proj / ".board"
    assert (board / "graph.db").exists()
    assert (board / "transitions.yaml").exists()
    assert (board / "nodetypes.yaml").read_text() == "types: {}\n"

    assert (proj / ".opencode" / "agents" / "gb.md").exists()
    assert list((proj / ".opencode" / "agents").glob("*.md")) == \
        [proj / ".opencode" / "agents" / "gb.md"]

    agents_md = (proj / "AGENTS.md").read_text()
    assert agents_md.startswith("This workspace coordinates")
    assert "role-instance" in agents_md

    config = json.loads((proj / "opencode.json").read_text())
    env = config["mcp"]["graphboard"]["environment"]
    assert env["GB_BOARD"] == str(board)
    assert env["GB_PROJECT"] == "myproj"
    assert env["GB_REPO"] == str(proj.resolve())
    assert config["tools"] == {"gba_*": False}
    assert config["agent"]["gb"]["tools"] == {"gba_*": True}
    bash = config["permission"]["bash"]
    assert bash["git push*"] == "deny"
    assert bash["git add -A*"] == "deny"
    assert bash["git commit -a*"] == "deny"

    assert not (proj / ".gitignore").exists()


def test_init_with_starter_template(tmp_path):
    proj = tmp_path / "myproj"
    assert cli.main(["init", str(proj), "--template", "branching"]) == 0
    grammar = (proj / ".board" / "transitions.yaml").read_text()
    assert "harvest" in grammar
    nodetypes = (proj / ".board" / "nodetypes.yaml").read_text()
    assert "review" in nodetypes


def test_init_with_extra_agents(tmp_path):
    proj = tmp_path / "myproj"
    assert cli.main(["init", str(proj), "--agents", "gb,proposal"]) == 0
    names = sorted(p.stem for p in (proj / ".opencode" / "agents").glob("*.md"))
    assert names == ["gb", "proposal"]


def test_init_git_matrix(tmp_path):
    plain = tmp_path / "plain"
    assert cli.main(["init", str(plain)]) == 0
    assert not (plain / ".gitignore").exists()

    withgit = tmp_path / "withgit"
    assert cli.main(["init", str(withgit), "--git"]) == 0
    assert (withgit / ".git").exists()
    gi = (withgit / ".gitignore").read_text()
    assert ".board/*.db" in gi and ".board/*.db-shm" in gi

    existing = tmp_path / "existing"
    existing.mkdir()
    subprocess.run(["git", "init"], cwd=existing, check=True, capture_output=True)
    assert cli.main(["init", str(existing)]) == 0
    gi = (existing / ".gitignore").read_text()
    assert ".board/*.db" in gi


def test_init_idempotent_agents_and_gitignore(tmp_path, capsys):
    proj = tmp_path / "myproj"
    assert cli.main(["init", str(proj), "--git"]) == 0
    capsys.readouterr()
    assert cli.main(["init", str(proj), "--git"]) == 0
    out = capsys.readouterr().out
    assert "agent skip" in out
    assert "AGENTS.md: skip" in out
    gi = (proj / ".gitignore").read_text()
    assert gi.count(".board/*.db\n") == 1


def test_rerun_keeps_board_force_reinits(tmp_path):
    proj = tmp_path / "myproj"
    assert cli.main(["init", str(proj)]) == 0
    assert cli.main(["--board", str(proj / ".board"), "propose",
                     "--type", "task", "--spec", "keep me"]) == 0
    assert cli.main(["init", str(proj)]) == 0
    assert cli.main(["--board", str(proj / ".board"), "list"]) == 0
    assert cli.main(["init", str(proj), "--force"]) == 0
    from graphboard import db
    conn = db.connect(proj / ".board" / "graph.db")
    count = conn.execute("SELECT COUNT(*) c FROM nodes").fetchone()["c"]
    conn.close()
    assert count == 0


def test_init_existing_opencode_json_merged(tmp_path):
    proj = tmp_path / "myproj"
    proj.mkdir()
    (proj / "opencode.json").write_text(json.dumps({
        "permission": {"edit": "ask",
                       "bash": {"git push*": "ask", "npm *": "allow"}}}))
    (proj / "AGENTS.md").write_text("# my rules\n")
    assert cli.main(["init", str(proj)]) == 0
    config = json.loads((proj / "opencode.json").read_text())
    edit = config["permission"]["edit"]
    assert edit["*"] == "ask"
    assert edit[".board/*"] == "deny"
    assert edit[".opencode/agents/*"] == "deny"
    assert edit["opencode.json"] == "deny"
    assert config["permission"]["bash"]["git push*"] == "ask"
    assert config["permission"]["bash"]["npm *"] == "allow"
    assert config["permission"]["bash"]["git rebase*"] == "deny"
    assert "graphboard" in config["mcp"]
    agents_md = (proj / "AGENTS.md").read_text()
    assert agents_md.startswith("# my rules")
    assert "graphboard" in agents_md
    assert "NOT a claim" in agents_md


def test_gitignore_covers_node_modules(tmp_path):
    proj = tmp_path / "myproj"
    assert cli.main(["init", str(proj), "--git"]) == 0
    gi = (proj / ".gitignore").read_text()
    assert ".opencode/node_modules/" in gi
