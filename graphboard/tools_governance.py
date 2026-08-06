from . import core, render, roles, scaffold
from .db import STATES
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

    @server.tool(description="GOVERNANCE (gb conductor only). Release an orphaned active (or blocked) "
                             "node back to pending after verifying its owner session is dead. The anchor "
                             "note is preserved so a new worker can re-pull and re-orient.")
    def gba_release(id: str, reason: str = "") -> str:
        def run(conn):
            core.release(conn, id, reason=reason)
            return render.render_release(id)
        return guard("gba_release", {"id": id, "reason": reason}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Cancel a non-terminal node on explicit human "
                             "instruction (superseded, abandoned, invalid). Terminal: owner/note preserved "
                             "for audit; resources freed.")
    def gba_cancel(id: str, reason: str = "") -> str:
        def run(conn):
            core.cancel(conn, id, reason=reason)
            return render.render_cancel(id)
        return guard("gba_cancel", {"id": id, "reason": reason}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Hold (defer) a proposed|pending node: it "
                             "becomes blocked and invisible to gb_pull until released. Use for human-"
                             "directed postponement.")
    def gba_hold(id: str, reason: str = "") -> str:
        def run(conn):
            core.hold(conn, id, reason=reason)
            return render.render_hold(id)
        return guard("gba_hold", {"id": id, "reason": reason}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Broadcast an announcement on explicit human "
                             "instruction; delivered to agents on their next gb_pull. audience: '*' (all), "
                             "a role name (e.g. experimenter) or an owner name. ttl_days: auto-expire "
                             "after N days (default: never).")
    def gba_announce(text: str, ttl_days: float = 0, audience: str = "*") -> str:
        def run(conn):
            ann_id = core.announce(conn, text=text, ttl_days=ttl_days or None,
                                   audience=audience or "*")
            return render.render_announce(ann_id, cleared=False,
                                          audience=audience or "*")
        return guard("gba_announce", {"text": text, "ttl_days": ttl_days,
                                      "audience": audience}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Re-prioritize a proposed|pending|blocked "
                             "node: level 1-9, lower is served first by gb_pull (default 3). Priority is "
                             "a scheduling hint, not a dependency.")
    def gba_priority(id: str, level: int, reason: str = "") -> str:
        def run(conn):
            core.set_priority(conn, id, int(level), reason=reason)
            return render.render_priority(id, int(level))
        return guard("gba_priority", {"id": id, "level": level, "reason": reason}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Append a directed message to a node (any "
                             "state, including done): delivered to matching agents at their next "
                             "gb_pull or gb_status(id, owner=<you>). audience: '*' (all), a role name "
                             "or an owner name. Use for directives and post-hoc notices; never for the "
                             "worker's anchor.")
    def gba_message(id: str, text: str, audience: str = "*") -> str:
        def run(conn):
            core.message(conn, id, author="conductor", text=text,
                         audience=audience or "*")
            return render.render_message(id, audience or "*")
        return guard("gba_message", {"id": id, "text": text,
                                     "audience": audience}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Facts store WRITE control. Reading is open "
                             "to all roles via gb_fact. action: set|remove|list.")
    def gba_fact(action: str = "list", key: str = "", value: str = "") -> str:
        def run(conn):
            if action == "set":
                core.fact_set(conn, key, value, by="conductor")
                return render.render_fact_set(key.strip())
            if action == "remove":
                core.fact_remove(conn, key, by="conductor")
                return render.render_fact_remove(key.strip())
            if action == "list":
                return render.render_facts(core.facts(conn))
            raise core.GbError(f"action must be set|remove|list, got {action!r}")
        return guard("gba_fact", {"action": action, "key": key,
                                  "value": value}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Project charter: what this project is about "
                             "and why. Written to .board/charter.md and baked into every role file at "
                             "generation (one-time background injection). action: show|set.")
    def gba_charter(action: str = "show", text: str = "") -> str:
        def run(conn):
            if action == "show":
                charter = core.charter_get(conn)
                return charter or render.render_charter("empty")
            if action == "set":
                core.charter_set(conn, text, by="conductor")
                return render.render_charter("set")
            raise core.GbError(f"action must be show|set, got {action!r}")
        return guard("gba_charter", {"action": action, "text": text}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Repair a node's summary: the one short line "
                             "shown in board views and pull injection. Keep it under ~120 chars; full "
                             "detail belongs in the spec / a design doc.")
    def gba_summary(id: str, text: str) -> str:
        def run(conn):
            core.set_summary(conn, id, text)
            return render.render_summary(id)
        return guard("gba_summary", {"id": id, "text": text}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Reopen a terminal node (done|rejected|"
                             "canceled) back to pending when the world changed after it was closed "
                             "(result invalidated, external process died). Anchor note preserved; the "
                             "repair is recorded in events.")
    def gba_reopen(id: str, reason: str = "") -> str:
        def run(conn):
            node = core.status(conn, id)["node"]
            core.reopen(conn, id, reason=reason)
            return render.render_reopen(id, node["state"])
        return guard("gba_reopen", {"id": id, "reason": reason}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Archive terminal node(s) to cold storage: "
                             "hidden from all live views (pull/query/status), restorable. under=true "
                             "archives the whole subtree; refused atomically if any member is "
                             "non-terminal.")
    def gba_archive(id: str, under: bool = False) -> str:
        def run(conn):
            count = core.archive(conn, id, under=under)
            return render.render_archive(id, count)
        return guard("gba_archive", {"id": id, "under": under}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Restore an archived node to live views "
                             "(state unchanged; combine with gba_reopen to resume closed work).")
    def gba_restore(id: str) -> str:
        def run(conn):
            core.restore(conn, id)
            return render.render_restore(id)
        return guard("gba_restore", {"id": id}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Atomically replace one node with another: "
                             "old (proposed|pending) is canceled with superseded_by recorded, new "
                             "(proposed) is approved in the same operation. One intent, one audit trail.")
    def gba_supersede(old_id: str, new_id: str, reason: str = "") -> str:
        def run(conn):
            result = core.supersede(conn, old_id, new_id, reason=reason)
            return render.render_supersede(result)
        return guard("gba_supersede", {"old_id": old_id, "new_id": new_id,
                                       "reason": reason}, run)

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

    @server.tool(description="GOVERNANCE (gb conductor only). Register or update a role after the human "
                             "confirmed the draft. action: register (new role) | update (full re-render of "
                             "an existing role - provide ALL slots again). claims: comma-separated node types. "
                             "background defaults to the board charter; the charter and the claimed types' "
                             "contracts are baked into the role file (one-time background injection). "
                             "Ensures node types exist and suggests grammar rules (never writes the grammar).")
    def gba_role(name: str, description: str, claims: str, duties: str = "",
                 loading: str = "", outputs: str = "", done_when: str = "",
                 action: str = "register", background: str = "") -> str:
        def run():
            repo = infra.repo()
            board_dir = infra.project_paths()
            claim_list = [c.strip() for c in claims.split(",") if c.strip()]
            if not claim_list:
                raise core.GbError("claims must list at least one node type")
            if action not in ("register", "update"):
                raise core.GbError(f"action must be register|update, got {action!r}")
            charter, contracts = roles.collect_role_context(board_dir, claim_list)
            content = roles.render_role(
                name=name, description=description, claims=claim_list,
                duties=duties or "Work the claimed node according to its spec and contract.",
                loading=loading or "Start from the node's inputs; use gb_query for anything else needed.",
                outputs=outputs or "Code artifacts stay in the repo (commit your own files with explicit "
                                   "pathspec before submit); coordination artifacts go to the workdir.",
                done_when=done_when or "The node spec's completion criteria are met and outputs are submitted.",
                background=(background or "").strip() or charter,
                contracts=contracts)
            path = roles.write_role(repo, name, content, force=(action == "update"))
            added = roles.ensure_nodetypes(board_dir, claim_list, description)
            lines = [f"role {'updated' if action == 'update' else 'registered'}: {path}"]
            if added:
                lines.append(f"node types added to nodetypes.yaml: {', '.join(added)}")
            lines.append(roles.suggest_grammar_rules(claim_list))
            lines.append("open a new session and switch to this role to use it")
            return "\n".join(lines)
        return guard_plain("gba_role", {"name": name, "description": description,
                                        "claims": claims, "action": action}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Grammar editing on explicit human instruction. "
                             "action: list|add|remove. Format: FROM_TYPE --event--> TO_TYPE (from_type/event/"
                             "to_type params). Unknown node types are auto-declared with a placeholder contract. "
                             "Validated before writing; swapped or invalid rules are refused. force=true accepts "
                             "a closed cycle without root (seedable via propose only).")
    def gba_grammar(action: str = "list", from_type: str = "", event: str = "",
                    to_type: str = "", frm: str = "", on: str = "", to: str = "",
                    activate: str = "approve", budget: int = 0,
                    force: bool = False) -> str:
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
                                            activate=activate, budget=budget or None,
                                            force=force)
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
                                           "activate": activate, "budget": budget,
                                           "force": force}, run)

    @server.tool(description="GOVERNANCE (gb conductor only). Dump the whole graph as markdown "
                             "(counts, facts, nodes by state). include_archived=true also lists "
                             "archived nodes.")
    def gba_export(include_archived: bool = False) -> str:
        def run(conn):
            overview = core.status(conn)
            lines = ["counts: " + ", ".join(f"{k}: {v}"
                                              for k, v in overview["counts"].items())]
            if overview.get("facts"):
                lines.append("facts:")
                lines.extend(f"  - {f['key']}: {f['value']}"
                             for f in overview["facts"])
            for state in STATES:
                rows = conn.execute(
                    "SELECT id, type, owner, spec FROM nodes "
                    "WHERE state=? AND archived=0 "
                    "ORDER BY priority ASC, created_at, rowid", (state,)).fetchall()
                if not rows:
                    continue
                lines.append(f"{state}:")
                for r in rows:
                    owner = f" [{r['owner']}]" if r["owner"] else ""
                    lines.append(f"  - {r['id']} ({r['type']}){owner} {r['spec']}")
            if include_archived:
                rows = conn.execute(
                    "SELECT id, type, state, spec FROM nodes WHERE archived=1 "
                    "ORDER BY created_at, rowid").fetchall()
                if rows:
                    lines.append("archived:")
                    lines.extend(f"  - {r['id']} ({r['type']}, {r['state']}) {r['spec']}"
                                 for r in rows)
            return "\n".join(lines)
        return guard("gba_export", {"include_archived": include_archived}, run)
