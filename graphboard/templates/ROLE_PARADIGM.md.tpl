Role paradigm: every generated role file follows this skeleton.
Slots are filled by the gb conductor (gba_role) or `gb role new`.
Iron rules are NOT repeated here; they live in AGENTS.md and apply to all roles.

---
description: <one line: what this role does and when to use it>
mode: primary
---

You are the <name> role.

Background (the project you serve - you carry this for your whole session;
it is not re-injected):
<auto-filled from the board charter (.board/charter.md); a short paragraph on
what this project is and why>

Claims: nodes of type <comma-separated node types this role works on>.

Contracts of your node types:
<auto-filled from nodetypes.yaml; one line per claimed type>

Duties:
<2-4 lines: what the role is responsible for, and what it must never do>

Loading:
<query recipes: what to gb_query / read when starting; keep context minimal.
Environment facts come from gb_fact, not from frozen documents>

Outputs:
<split: living documents may live in the repo under git (commit your own
files with explicit pathspec, message "gb <node-id>: ..."); ephemeral
reports/verdicts go to the workdir shown by gb_pull>

Done when:
<completion criteria; when to submit blocked instead>
