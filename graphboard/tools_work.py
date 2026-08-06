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

    @server.tool(description="Finish the active node, or harvest a running one. status: done|blocked; "
                             "event overrides the grammar event (default: status). outputs: PATH[:NOTE];PATH. "
                             "successors: TYPE|SPEC;TYPE|SPEC (grammar decides auto vs approval). "
                             "Declare every successor the workflow expects.")
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

    @server.tool(description="Delegate an active node to autonomous execution (long training/build/"
                             "pipeline/external wait): you launched it in the background, now detach and "
                             "move on - do NOT wait. resources: held resource labels (e.g. gpu:srv1;"
                             "machine:srv2). note: how to check it later (tmux/log coords). check_after: "
                             "when to come back and harvest (ISO time). Harvest later via gb_submit.")
    def gb_delegate(id: str, owner: str, resources: str = "", note: str = "",
                    check_after: str = "") -> str:
        def run(conn):
            result = core.delegate(conn, id, owner=owner, resources=resources,
                                   note=note or None, check_after=check_after or None)
            return render.render_delegate(result)
        return guard("gb_delegate", {"id": id, "owner": owner,
                                     "resources": resources, "note": note,
                                     "check_after": check_after}, run)

    @server.tool(description="Reclaim a running node's attention (running -> active): the autonomous "
                             "work crashed and needs hands-on fixing, or you continue it manually. "
                             "Caller becomes the owner.")
    def gb_reactivate(id: str, owner: str) -> str:
        def run(conn):
            result = core.reactivate(conn, id, owner=owner)
            return render.render_reactivate(result)
        return guard("gb_reactivate", {"id": id, "owner": owner}, run)

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

    @server.tool(description="Board overview (no id) or one node's lineage, children, outputs, messages "
                             "(with id). Re-orient here after a session restart or context compaction: "
                             "pass your owner name to see your own active/running nodes first.")
    def gb_status(id: str = "", owner: str = "") -> str:
        def run(conn):
            result = core.status(conn, id or None, owner=owner or None)
            return render.render_status(result)
        return guard("gb_status", {"id": id, "owner": owner}, run)

    @server.tool(description="Query nodes by any mix of type/state/under(subtree of a node id, inclusive)/"
                             "owner. Compact list with output paths and held resources (for running nodes); "
                             "read specific files natively afterwards. Use state=running to see which "
                             "resources are occupied before claiming resource-consuming work.")
    def gb_query(type: str = "", state: str = "", under: str = "", owner: str = "",
                 limit: int = 20) -> str:
        def run(conn):
            result = core.query(conn, type=type or None, state=state or None,
                                under=under or None, owner=owner or None, limit=limit)
            return render.render_query(result)
        return guard("gb_query", {"type": type, "state": state, "under": under,
                                  "owner": owner, "limit": limit}, run)

    @server.tool(description="Replace the anchor note on a node you own (current position, progress, "
                             "sync point). Pass your owner name; anchors are owner-writable. Directives "
                             "to other roles are governance messages, not anchors.")
    def gb_note(id: str, text: str, owner: str) -> str:
        def run(conn):
            core.note(conn, id, text, owner=owner)
            return render.render_note(id)
        return guard("gb_note", {"id": id, "text": text, "owner": owner}, run)

    @server.tool(description="Read-only board health check. Run it when something feels off.")
    def gb_doctor() -> str:
        def run(conn):
            board = infra.project_paths()
            grammar, _ = infra.grammar_and_contracts()
            ok, issues = doctor.run_checks(conn, board, grammar)
            return doctor.render_report(ok, issues)
        return guard("gb_doctor", {}, run)
