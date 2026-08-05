from . import core, doctor, render


def register(server, infra):
    guard = infra.guard

    @server.tool(description="Claim the next pending node and get what you need to start. "
                             "owner: your role-instance name (e.g. impl-a).")
    def gb_pull(owner: str, type: str = "") -> str:
        def run(conn):
            grammar, contracts = infra.grammar_and_contracts()
            result = core.pull(conn, owner, type_filter=type or None,
                               contracts=contracts)
            if result.get("claimed"):
                baseline = infra.baseline_str()
                if baseline:
                    result["claimed"]["baseline"] = baseline
            return render.render_pull(result)
        return guard("gb_pull", {"owner": owner, "type": type}, run)

    @server.tool(description="Finish the active node. status: done|blocked; event overrides the grammar "
                             "event (default: status). outputs: PATH[:NOTE];PATH. successors: "
                             "TYPE|SPEC;TYPE|SPEC (grammar decides auto vs approval).")
    def gb_submit(id: str, owner: str, status: str, event: str = "", note: str = "",
                  outputs: str = "", successors: str = "") -> str:
        def run(conn):
            grammar, _ = infra.grammar_and_contracts()
            result = core.submit(conn, id, owner=owner, status=status,
                                 outputs=core.parse_outputs(outputs),
                                 successors=core.parse_successors(successors),
                                 event=event or None, note=note or None,
                                 grammar=grammar)
            return render.render_submit(result)
        return guard("gb_submit", {"id": id, "owner": owner, "status": status,
                                   "event": event, "note": note,
                                   "outputs": outputs, "successors": successors}, run)

    @server.tool(description="Split an active node into smaller children when the work grew too big. "
                             "children: TYPE|SPEC;TYPE|SPEC. The node becomes blocked and unowned; when "
                             "all children are done it returns to pending for integration. Each child "
                             "spec must be self-contained for a fresh session.")
    def gb_split(id: str, owner: str, children: str) -> str:
        def run(conn):
            grammar, _ = infra.grammar_and_contracts()
            result = core.split(conn, id, owner=owner,
                                children=core.parse_successors(children),
                                grammar=grammar)
            return render.render_split(result)
        return guard("gb_split", {"id": id, "owner": owner, "children": children}, run)

    @server.tool(description="Propose a new node (needs approval unless a grammar rule says otherwise).")
    def gb_propose(type: str, spec: str, parent: str = "") -> str:
        def run(conn):
            nid = core.propose(conn, type, spec, parent=parent or None)
            return render.render_propose(nid)
        return guard("gb_propose", {"type": type, "spec": spec, "parent": parent}, run)

    @server.tool(description="Board overview (no id) or one node's lineage, children, outputs (with id). "
                             "Re-orient here after context compaction.")
    def gb_status(id: str = "") -> str:
        def run(conn):
            result = core.status(conn, id or None)
            return render.render_status(result)
        return guard("gb_status", {"id": id}, run)

    @server.tool(description="Query nodes by any mix of type/state/under(subtree of a node id, inclusive)/"
                             "owner. Compact list with output paths; read specific files natively afterwards.")
    def gb_query(type: str = "", state: str = "", under: str = "", owner: str = "",
                 limit: int = 20) -> str:
        def run(conn):
            result = core.query(conn, type=type or None, state=state or None,
                                under=under or None, owner=owner or None, limit=limit)
            return render.render_query(result)
        return guard("gb_query", {"type": type, "state": state, "under": under,
                                  "owner": owner, "limit": limit}, run)

    @server.tool(description="Replace the node's anchor note (current position, progress, sync point).")
    def gb_note(id: str, text: str) -> str:
        def run(conn):
            core.note(conn, id, text)
            return render.render_note(id)
        return guard("gb_note", {"id": id, "text": text}, run)

    @server.tool(description="Read-only board health check. Run it when something feels off.")
    def gb_doctor() -> str:
        def run(conn):
            board = infra.project_paths()
            grammar, _ = infra.grammar_and_contracts()
            ok, issues = doctor.run_checks(conn, board, grammar)
            return doctor.render_report(ok, issues)
        return guard("gb_doctor", {}, run)
