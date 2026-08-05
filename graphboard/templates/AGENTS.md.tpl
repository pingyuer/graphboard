This workspace coordinates work through graphboard. Rules for every agent:

1. Start work with gb_pull using an owner name in role-instance format (e.g. impl-a, review-b); claim a node, then work ONLY on that node. A gb_note is NOT a claim: ownership begins only when gb_pull returns claimed:. If nothing is pending but nodes of your type await approval, wait or ask the human — do not start working.
2. Load context on demand: the node's inputs plus what gb_query finds relevant; read specific files natively. Never roam the board.
3. Record progress with gb_note; finish with gb_submit (declare successors when the workflow expects them). Living documents (proposals, designs) may live in the repo under git; ephemeral reports and verdicts go to the workdir shown by gb_pull. If a node grows too big mid-work, split it with gb_split into self-contained children; each child spec must make sense to a fresh session on its own.
4. Git discipline (when the repo uses git): keep the baseline shown by gb_pull as your sync point. Commit ONLY files you changed, with explicit pathspec and message "gb <node-id>: summary"; commit your work before gb_submit. NEVER: git add -A, git commit -a, push, merge, rebase, switch branches, reset --hard. The human and other agents also change the tree — if the code changed under you, diff against your baseline and re-orient.
5. If lost, or after context compaction: call gb_status to re-orient before doing anything else.
6. Approval, announcements, roles and the grammar belong to the gb conductor role and the human; never act beyond the current node.
