import pytest

from graphboard import roles, scaffold
from graphboard.core import GbError
from graphboard.gitutil import git_baseline
from graphboard.grammar import (GrammarError, grammar_add_rule,
                                grammar_remove_rule, load)


@pytest.fixture
def project(tmp_path):
    board, _ = scaffold.init_board(tmp_path / "board" / "p",
                                   template="rd-classic")
    return board


def test_render_role_structure():
    text = roles.render_role(
        "tuner", "Tunes perf.", ["implementation"],
        "Profile then optimize.", "Query benchmarks.",
        "Code stays in repo.", "Benchmarks improve.")
    assert text.startswith("---\ndescription: Tunes perf.\nmode: primary\n---")
    assert "You are the tuner role" in text
    assert "Claims: nodes of type implementation." in text
    assert "Done when:\nBenchmarks improve." in text


def test_write_role_and_listing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    content = roles.render_role("tuner", "d", ["implementation"],
                                "x", "y", "z", "w")
    path = roles.write_role(repo, "tuner", content)
    assert path.read_text() == content
    with pytest.raises(GbError, match="already exists"):
        roles.write_role(repo, "tuner", content)
    roles.write_role(repo, "tuner", content, force=True)
    with pytest.raises(GbError, match="lowercase"):
        roles.write_role(repo, "Bad_Name", content)
    found = roles.list_roles(repo)
    assert found[0]["name"] == "tuner"
    assert found[0]["description"] == "d"


def test_ensure_nodetypes_idempotent(project):
    added = roles.ensure_nodetypes(project, ["survey", "proposal"], "Scout docs.")
    assert added == ["survey"]
    added = roles.ensure_nodetypes(project, ["survey"], "Scout docs.")
    assert added == []


def test_grammar_add_remove_validated(project):
    grammar_add_rule(project, "proposal", "done", "docs")
    g = load(project / "transitions.yaml")
    assert any(r.frm == "proposal" and r.to == "docs" for r in g.rules)

    with pytest.raises(GrammarError, match="rejected by grammar-check"):
        grammar_add_rule(project, "acceptance", "explode", "proposal")
    g = load(project / "transitions.yaml")
    assert not any(r.on == "explode" for r in g.rules)

    grammar_remove_rule(project, "proposal", "done", "docs")
    g = load(project / "transitions.yaml")
    assert not any(r.to == "docs" for r in g.rules)
    with pytest.raises(GrammarError, match="no such rule"):
        grammar_remove_rule(project, "proposal", "done", "docs")


def test_grammar_add_cycle_refused(project):
    with pytest.raises(GrammarError, match="auto cycle"):
        grammar_add_rule(project, "acceptance", "fail",
                         "implementation", activate="auto")


def test_init_board_keeps_and_reinit(tmp_path):
    board = tmp_path / "x"
    _, action = scaffold.init_board(board, template="minimal")
    assert action == "created"
    assert (board / "nodetypes.yaml").read_text() == "types: {}\n"
    _, action = scaffold.init_board(board, template="minimal")
    assert action == "kept"
    _, action = scaffold.init_board(board, template="minimal", force=True)
    assert action == "reinit"


def test_scaffold_project_full(tmp_path):
    result = scaffold.scaffold_project(tmp_path / "proj", name="demo",
                                       template="minimal", git=False)
    assert result["project"] == "demo"
    assert (result["board"] / "graph.db").exists()
    assert (result["repo"] / ".opencode" / "agents" / "gb.md").exists()
    assert result["git"] == "skip"


def test_available_agent_templates():
    assert "gb" in scaffold.available_agent_templates()


def test_grammar_add_rejects_swapped_rule(project):
    with pytest.raises(GrammarError, match="looks swapped"):
        grammar_add_rule(project, "done", "proposal", "implementation")
    with pytest.raises(GrammarError, match="looks swapped"):
        grammar_add_rule(project, "mystery", "implementation", "acceptance")
    findings = grammar_add_rule(project, "proposal", "done", "docs2")
    assert isinstance(findings, list)


def test_git_baseline(tmp_path):
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    assert git_baseline(repo) is None
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    assert git_baseline(repo) is None
    (repo / "a.txt").write_text("x")
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-m", "init"], cwd=repo, check=True,
                   capture_output=True)
    b = git_baseline(repo)
    assert b["dirty"] == 0 and b["hash"]
    (repo / "b.txt").write_text("y")
    b = git_baseline(repo)
    assert b["dirty"] == 1
