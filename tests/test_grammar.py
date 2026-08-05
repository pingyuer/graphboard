import pytest

from graphboard import grammar as G


@pytest.fixture
def g():
    return G.Grammar(default="approve", rules=[
        G.Rule("proposal", "done", "implementation", "approve"),
        G.Rule("implementation", "done", "acceptance", "auto"),
        G.Rule("acceptance", "fail", "implementation", "auto", budget=3),
        G.Rule("any", "blocked", "any", "approve"),
    ])


def test_evaluate_exact_match(g):
    activate, rule = G.evaluate(g, "implementation", "done", "acceptance")
    assert activate == "auto"
    assert rule.budget is None


def test_evaluate_specificity_prefers_exact_over_any():
    g = G.Grammar(rules=[
        G.Rule("any", "done", "any", "approve"),
        G.Rule("a", "done", "b", "auto"),
    ])
    activate, rule = G.evaluate(g, "a", "done", "b")
    assert activate == "auto"
    activate, rule = G.evaluate(g, "a", "done", "c")
    assert activate == "approve"


def test_evaluate_no_match_falls_to_default():
    g = G.Grammar(default="approve", rules=[])
    activate, rule = G.evaluate(g, "x", "done", "y")
    assert activate == "approve" and rule is None


def test_check_clean_grammar_passes(g):
    nodetypes = {
        "proposal": {"emits": ["done"]},
        "implementation": {"emits": ["done", "blocked"]},
        "acceptance": {"emits": ["done", "fail"]},
    }
    findings = G.check(g, nodetypes)
    assert not [f for f in findings if f[0] == "error"], findings


def test_check_illegal_event():
    g = G.Grammar(rules=[G.Rule("a", "explode", "b", "auto")])
    findings = G.check(g, {"a": {"emits": ["done"]}, "b": {}})
    assert any(f[0] == "error" and "explode" in f[1] for f in findings)


def test_check_auto_cycle_without_budget_errors():
    g = G.Grammar(rules=[
        G.Rule("a", "done", "b", "auto"),
        G.Rule("b", "done", "a", "auto"),
    ])
    findings = G.check(g, {})
    assert any(f[0] == "error" and "auto cycle" in f[1] for f in findings)


def test_check_auto_cycle_with_budget_ok():
    g = G.Grammar(rules=[
        G.Rule("a", "done", "b", "auto"),
        G.Rule("b", "done", "a", "auto", budget=3),
    ])
    findings = G.check(g, {})
    assert not [f for f in findings if f[0] == "error" and "auto cycle" in f[1]]


def test_check_any_auto_warns():
    g = G.Grammar(rules=[G.Rule("any", "blocked", "any", "auto")])
    findings = G.check(g, {})
    assert any(f[0] == "warning" and "any" in f[1] for f in findings)


def test_check_closed_cycle_no_root_errors():
    g = G.Grammar(rules=[
        G.Rule("a", "done", "b", "approve"),
        G.Rule("b", "done", "a", "approve"),
    ])
    findings = G.check(g, {})
    assert any(f[0] == "error" and "no root" in f[1] for f in findings)


def test_check_unreachable_type_warns():
    g = G.Grammar(rules=[G.Rule("a", "done", "b", "approve")])
    findings = G.check(g, {"a": {}, "b": {}, "orphan": {}})
    assert any(f[0] == "warning" and "orphan" in f[1] for f in findings)


def test_check_undefined_to_type_warns():
    g = G.Grammar(rules=[G.Rule("a", "done", "ghost", "approve")])
    findings = G.check(g, {"a": {}})
    assert any(f[0] == "warning" and "ghost" in f[1] for f in findings)


def test_load_and_load_nodetypes(tmp_path):
    p = tmp_path / "t.yaml"
    p.write_text(
        "default: approve\n"
        "transitions:\n"
        "  - {from: a, on: done, to: b, activate: auto, budget: 2}\n",
        encoding="utf-8")
    g = G.load(p)
    assert g.default == "approve"
    assert g.rules[0].budget == 2
    nt = tmp_path / "nt.yaml"
    nt.write_text("types:\n  a: {emits: [done]}\n", encoding="utf-8")
    assert G.load_nodetypes(nt)["a"]["emits"] == ["done"]
    assert G.load_nodetypes(tmp_path / "missing.yaml") == {}


def test_load_rejects_bad_activate(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("transitions:\n  - {from: a, on: done, to: b, activate: yolo}\n")
    with pytest.raises(G.GrammarError):
        G.load(p)
