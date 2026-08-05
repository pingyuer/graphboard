from dataclasses import dataclass, field
from pathlib import Path

import yaml

UNIVERSAL_EVENTS = ("done", "blocked")
ACTIVATE_MODES = ("auto", "approve")
EVENT_WORDS = {"done", "blocked", "fail", "approved", "rejected"}
PLACEHOLDER_CONTRACT = ("TODO: describe this node type's contract "
                        "(auto-declared placeholder)")


def declare_nodetype(board_dir, ntype, contract=None):
    path = Path(board_dir) / "nodetypes.yaml"
    data = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    types = data.setdefault("types", {})
    if ntype in types:
        return False
    types[ntype] = {"emits": list(UNIVERSAL_EVENTS),
                    "contract": contract or PLACEHOLDER_CONTRACT}
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")
    return True


@dataclass
class Rule:
    frm: str
    on: str
    to: str
    activate: str = "approve"
    budget: int | None = None


@dataclass
class Grammar:
    default: str = "approve"
    rules: list = field(default_factory=list)


class GrammarError(ValueError):
    pass


def load(path) -> Grammar:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return parse_data(data, str(path))


def parse_data(data, source="<memory>") -> Grammar:
    if not isinstance(data, dict):
        raise GrammarError(f"grammar root must be a mapping: {source}")
    default = data.get("default", "approve")
    if default not in ACTIVATE_MODES:
        raise GrammarError(f"default must be one of {ACTIVATE_MODES}, got {default!r}")
    rules = []
    for i, raw in enumerate(data.get("transitions") or []):
        if not isinstance(raw, dict):
            raise GrammarError(f"transition #{i} must be a mapping")
        frm = raw.get("from")
        on = raw.get("on", raw.get(True))
        to = raw.get("to")
        if not frm or not on or not to:
            raise GrammarError(f"transition #{i} missing 'from'/'on'/'to'")
        activate = raw.get("activate", "approve")
        if activate not in ACTIVATE_MODES:
            raise GrammarError(f"transition #{i} activate must be one of {ACTIVATE_MODES}")
        budget = raw.get("budget")
        if budget is not None and (not isinstance(budget, int) or budget < 1):
            raise GrammarError(f"transition #{i} budget must be a positive integer")
        rules.append(Rule(frm=frm, on=on, to=to, activate=activate, budget=budget))
    return Grammar(default=default, rules=rules)


def load_nodetypes(path):
    p = Path(path)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    types = data.get("types") or {}
    if not isinstance(types, dict):
        raise GrammarError(f"nodetypes 'types' must be a mapping: {path}")
    return types


def evaluate(g: Grammar, from_type: str, on: str, to_type: str):
    best, best_score = None, -1
    for r in g.rules:
        if r.on != on:
            continue
        frm_ok = r.frm == from_type or r.frm == "any"
        to_ok = r.to == to_type or r.to == "any"
        if not (frm_ok and to_ok):
            continue
        score = (2 if r.frm == from_type else 0) + (2 if r.to == to_type else 0)
        if score > best_score:
            best, best_score = r, score
    if best is None:
        return g.default, None
    return best.activate, best


def check(g: Grammar, nodetypes: dict | None = None):
    nodetypes = nodetypes or {}
    findings = []

    for r in g.rules:
        if r.frm == "any":
            continue
        emits = (nodetypes.get(r.frm) or {}).get("emits")
        if emits is None:
            continue
        allowed = set(emits) | set(UNIVERSAL_EVENTS)
        if r.on not in allowed:
            findings.append(("error",
                f"rule {r.frm}--{r.on}-->{r.to}: event '{r.on}' not emitted by "
                f"type '{r.frm}' (declared emits: {sorted(emits)})"))

    auto_edges, any_auto = [], False
    for r in g.rules:
        if r.activate != "auto":
            continue
        if r.frm == "any" or r.to == "any":
            any_auto = True
            continue
        auto_edges.append(r)
    if any_auto:
        findings.append(("warning",
            "auto rule with 'any' endpoint: cycle cannot be statically verified"))
    for cycle in _find_cycles(auto_edges):
        if not any(r.budget for r in cycle):
            desc = " --> ".join([cycle[0].frm] + [r.to for r in cycle])
            findings.append(("error",
                f"auto cycle without budget: {desc}; add 'budget: N' to one of its rules"))

    concrete = set()
    adj = {}
    indeg = {}
    for r in g.rules:
        if r.frm != "any":
            concrete.add(r.frm)
        if r.to != "any":
            concrete.add(r.to)
    concrete |= set(nodetypes.keys())
    for t in concrete:
        adj.setdefault(t, set())
        indeg.setdefault(t, 0)
    for r in g.rules:
        if r.frm == "any" or r.to == "any":
            continue
        if r.to not in adj[r.frm]:
            adj[r.frm].add(r.to)
            indeg[r.to] += 1
    roots = [t for t in concrete if indeg[t] == 0]
    has_edges = any(adj.values())
    if has_edges and not roots:
        findings.append(("error",
            "type graph is a closed cycle with no root: no entry point for work"))
    if roots:
        seen = set()
        stack = list(roots)
        while stack:
            t = stack.pop()
            if t in seen:
                continue
            seen.add(t)
            stack.extend(adj.get(t, ()))
        for t in sorted(concrete - seen):
            findings.append(("warning", f"type '{t}' unreachable from any root"))
    for t in sorted(concrete):
        if indeg[t] == 0 and not adj.get(t):
            findings.append(("warning", f"type '{t}' is isolated (no edges)"))

    for r in g.rules:
        for t in (r.frm, r.to):
            if t != "any" and nodetypes and t not in nodetypes:
                findings.append(("warning",
                    f"type '{t}' referenced but not defined in nodetypes"))

    return findings


def _find_cycles(rules):
    adj = {}
    by_edge = {}
    for r in rules:
        adj.setdefault(r.frm, []).append(r.to)
        by_edge[(r.frm, r.to)] = r
    cycles = []
    seen_global = set()

    def dfs(node, path, on_path):
        for nxt in adj.get(node, ()):
            if nxt in on_path:
                i = path.index(nxt)
                cyc_nodes = path[i:] + [nxt]
                cyc_rules = [by_edge[(a, b)] for a, b in zip(cyc_nodes, cyc_nodes[1:])]
                key = frozenset((r.frm, r.on, r.to) for r in cyc_rules)
                if key not in seen_global:
                    seen_global.add(key)
                    cycles.append(cyc_rules)
            else:
                on_path.add(nxt)
                path.append(nxt)
                dfs(nxt, path, on_path)
                path.pop()
                on_path.discard(nxt)

    for start in list(adj):
        dfs(start, [start], {start})
    return cycles


def _load_raw_grammar(board_dir):
    path = Path(board_dir) / "transitions.yaml"
    if not path.exists():
        raise GrammarError(f"no grammar at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return path, data


def grammar_add_rule(board_dir, frm, on, to, activate="approve", budget=None,
                     force=False):
    path, data = _load_raw_grammar(board_dir)
    nodetypes = load_nodetypes(Path(board_dir) / "nodetypes.yaml")
    if frm in EVENT_WORDS:
        raise GrammarError(
            f"looks swapped: from_type should be a node type, not the event "
            f"'{frm}'. Rule format: FROM_TYPE --event--> TO_TYPE, e.g. "
            f"proposal --done--> implementation")
    if nodetypes and on in nodetypes and frm not in nodetypes and frm != "any":
        raise GrammarError(
            f"looks swapped: '{on}' is a known node type used as the event. "
            f"Rule format: FROM_TYPE --event--> TO_TYPE")
    findings_extra = []
    for t in (frm, to):
        if t != "any" and t not in nodetypes:
            declare_nodetype(board_dir, t)
            findings_extra.append(("info",
                f"auto-declared node type '{t}' with placeholder contract - "
                f"fill in the real contract in nodetypes.yaml"))
    rule = {"from": frm, "on": on, "to": to, "activate": activate}
    if budget:
        rule["budget"] = int(budget)
    candidate = dict(data)
    candidate["transitions"] = list(data.get("transitions") or []) + [rule]
    parsed = parse_data(candidate)
    findings = findings_extra + check(parsed, load_nodetypes(Path(board_dir) / "nodetypes.yaml"))
    errors = [m for lvl, m in findings if lvl == "error"]
    if force:
        errors = [m for m in errors if "no root" not in m]
        findings = [(("warning" if lvl == "error" and "no root" in msg else lvl), msg)
                    for lvl, msg in findings]
    if errors:
        msg = "rule rejected by grammar-check: " + "; ".join(errors)
        if any("no root" in e for e in errors):
            msg += (" | fixes: add an entry rule first (e.g. goal --done--> "
                    "<one of your types>), or re-run with force=true to accept "
                    "a closed cycle (it can then only be seeded via propose)")
        raise GrammarError(msg)
    path.write_text(yaml.safe_dump(candidate, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")
    return findings


def grammar_remove_rule(board_dir, frm, on, to):
    path, data = _load_raw_grammar(board_dir)
    transitions = data.get("transitions") or []
    kept = []
    removed = 0
    for raw in transitions:
        r = dict(raw)
        r_on = r.get("on", r.get(True))
        if r.get("from") == frm and r_on == on and r.get("to") == to:
            removed += 1
            continue
        kept.append(raw)
    if removed == 0:
        raise GrammarError(f"no such rule: {frm} --{on}--> {to}")
    data["transitions"] = kept
    parsed = parse_data(data)
    findings = check(parsed, load_nodetypes(Path(board_dir) / "nodetypes.yaml"))
    errors = [f for f in findings if f[0] == "error"]
    if errors:
        raise GrammarError("removal rejected by grammar-check: " +
                           "; ".join(msg for _, msg in errors))
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")
    return findings
