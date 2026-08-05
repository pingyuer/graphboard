from . import core, render, roles, scaffold
from .grammar import grammar_add_rule, grammar_remove_rule, load


def register(server, infra):
    guard, guard_plain = infra.guard, infra.guard_plain

    @server.tool(description="GOVERNANCE (gb conductor only). Approve a proposed node on explicit human "
                             "instruction; set reject=true to reject instead.")
    def gba_approve(id: str, spec_edit: str = "", reject: bool = False) -> str:
        def run(conn):
            if reject:
                core.reject(conn, id)
                return render.render_reject(id)
            core.approve(conn, id, spec_edit=spec_edit or None)
            return render.render_approve(id)
        return guard("gba_approve", {"id": id, "spec_edit": spec_edit, "reject": reject}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Broadcast an announcement on explicit human "
                             "instruction; delivered to agents on their next gb_pull.")
    def gba_announce(text: str) -> str:
        def run(conn):
            ann_id = core.announce(conn, text=text)
            return render.render_announce(ann_id, cleared=False)
        return guard("gba_announce", {"text": text}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Create the board if missing. "
                             "template: minimal|rd-classic|experiment|branching.")
    def gba_bootstrap(template: str = "minimal") -> str:
        def run():
            d = infra.resolve_board_dir()
            if (d / "graph.db").exists():
                return f"board already initialized at {d}"
            scaffold.init_board(d, template=template)
            return f"bootstrapped board at {d} (template: {template})"
        return guard_plain("gba_bootstrap", {"template": template}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Register a new role after the human confirmed "
                             "the draft. claims: comma-separated node types. Ensures node types exist and "
                             "suggests grammar rules (never writes the grammar).")
    def gba_role(name: str, description: str, claims: str, duties: str = "",
                 loading: str = "", outputs: str = "", done_when: str = "") -> str:
        def run():
            repo = infra.repo()
            board_dir = infra.project_paths()
            claim_list = [c.strip() for c in claims.split(",") if c.strip()]
            if not claim_list:
                raise core.GbError("claims must list at least one node type")
            content = roles.render_role(
                name=name, description=description, claims=claim_list,
                duties=duties or "Work the claimed node according to its spec and contract.",
                loading=loading or "Start from the node's inputs; use gb_query for anything else needed.",
                outputs=outputs or "Code artifacts stay in the repo (commit your own files with explicit "
                                   "pathspec before submit); coordination artifacts go to the workdir.",
                done_when=done_when or "The node spec's completion criteria are met and outputs are submitted.")
            path = roles.write_role(repo, name, content)
            added = roles.ensure_nodetypes(board_dir, claim_list, description)
            lines = [f"role registered: {path}"]
            if added:
                lines.append(f"node types added to nodetypes.yaml: {', '.join(added)}")
            lines.append(roles.suggest_grammar_rules(claim_list))
            lines.append("open a new session and switch to this role to use it")
            return "\n".join(lines)
        return guard_plain("gba_role", {"name": name, "description": description,
                                        "claims": claims}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Grammar editing on explicit human instruction. "
                             "action: list|add|remove. Format: FROM_TYPE --event--> TO_TYPE (from_type/event/"
                             "to_type params). Validated before writing; swapped or invalid rules are refused.")
    def gba_grammar(action: str = "list", from_type: str = "", event: str = "",
                    to_type: str = "", frm: str = "", on: str = "", to: str = "",
                    activate: str = "approve", budget: int = 0) -> str:
        frm = from_type or frm
        on = event or on
        to = to_type or to

        def run():
            board_dir = infra.project_paths()
            if action == "list":
                g = load(board_dir / "transitions.yaml")
                lines = [f"default: {g.default}"]
                for r in g.rules:
                    b = f" budget={r.budget}" if r.budget else ""
                    lines.append(f"  {r.frm} --{r.on}--> {r.to} [{r.activate}]{b}")
                return "\n".join(lines)
            if action == "add":
                findings = grammar_add_rule(board_dir, frm, on, to,
                                            activate=activate, budget=budget or None)
            elif action == "remove":
                findings = grammar_remove_rule(board_dir, frm, on, to)
            else:
                raise core.GbError(f"action must be list|add|remove, got {action!r}")
            lines = [f"grammar updated: {frm} --{on}--> {to}"]
            for level, msg in findings:
                lines.append(f"{level}: {msg}")
            if not findings:
                lines.append("grammar-check: OK")
            return "\n".join(lines)
        return guard_plain("gba_grammar", {"action": action, "from_type": frm,
                                           "event": on, "to_type": to,
                                           "activate": activate, "budget": budget}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Dump the whole graph as markdown "
                             "(counts, nodes by state).")
    def gba_export() -> str:
        def run(conn):
            overview = core.status(conn)
            lines = ["counts: " + ", ".join(f"{k}: {v}"
                                             for k, v in overview["counts"].items())]
            for state in ("active", "pending", "proposed", "blocked", "done", "rejected"):
                rows = conn.execute(
                    "SELECT id, type, owner, spec FROM nodes WHERE state=? "
                    "ORDER BY created_at", (state,)).fetchall()
                if not rows:
                    continue
                lines.append(f"{state}:")
                for r in rows:
                    owner = f" [{r['owner']}]" if r["owner"] else ""
                    lines.append(f"  - {r['id']} ({r['type']}){owner} {r['spec']}")
            return "\n".join(lines)
        return guard("gba_export", {}, run)
