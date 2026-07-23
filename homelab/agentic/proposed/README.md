# proposed/ — candidate skills & rules awaiting your approval

When recurring work suggests a new **skill** (a repeatable procedure) or **rule** (a standing
behavior), a session drops a *proposal* here instead of silently reimplementing it or acting
on an unwritten habit. Proposals are inert drafts — they do nothing until you promote them.

**Lifecycle:**
1. **Capture** — `python3 homelab/agentic/propose.py create --kind skill|rule --name <slug> --desc "..." --rationale "..." [--body-file F]`
2. **Review** — proposals appear on the rpi webapp Agentic Workspace page under "Proposed".
3. **Promote / Dismiss** — from the webapp (buttons, via the opti dispatcher) or the CLI:
   - `propose.py promote <id>` → materializes `skills/<name>/SKILL.md` or `rules/<name>.md`
   - `propose.py dismiss <id>` → discards the draft

Each proposal file is `<kind>-<slug>.md` with frontmatter (kind, name, description, rationale,
status, created, created_by) and a Markdown body that becomes the skill procedure / rule text.

This is deliberately human-in-the-loop: trends *suggest*, you *decide*. Nothing here auto-writes
into your live skills or rules.
