# Rule: reach homelab hosts through the skill, not ad-hoc ssh

When a task names `opti`, `rpi`, `noblenumbat`, or `android` **and** acting on it needs real
shell access, use the [`homelab-ssh`](../skills/homelab-ssh/SKILL.md) skill instead of
hand-writing an `ssh` invocation.

**Why:** connection details drift, and a hand-rolled command carrying a stale key path or port
fails in a way that reads like "the host is down". android's port and user are non-standard
(8022, `u0_a204`), and the interactive key (`~/.ssh/homelab`) is **not** the key the collectors
use (`~/.ssh/hl_agents`). The skill points at `~/.ssh/config` and the hosts runbook — the
things that actually get updated when something changes.

**How to apply:**

- Prefer the configured alias: `ssh opti '<cmd>'`. The alias already carries user, port and
  identity file, so don't pass `-i` or `-p` without a specific reason.
- Unsure what an alias resolves to? Ask, don't guess:
  `ssh -G <alias> | grep -iE '^(hostname|port|user|identityfile) '`
- Read-only checks (`docker ps`, `df -h`, `systemctl status`, logs) need no approval — run
  them. State-changing commands: say what you're about to do in one line, then run it.
- If an alias isn't configured, consult
  [`../runbooks/01-hosts-and-ssh.md`](../runbooks/01-hosts-and-ssh.md) rather than inventing a
  key path. Don't assume one host's key works on another.

**Exception:** the collectors in `homelab/Tools/homelab/` deliberately do their own SSH fan-out
via `_hosts.py` and the `hl_agents` key. Don't rewrite those to use the interactive alias —
they run unattended on opti, where `~/.ssh/config` aliases aren't in play.
