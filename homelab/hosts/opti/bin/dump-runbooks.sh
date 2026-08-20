#!/bin/bash
# Dumps the authored homelab runbooks as a JSON array of {name, content}, so the
# phone's local LLM can read them live over SSH with no local sync/copy needed.
# Runs on opti. Deployed at opti:~/bin/dump-runbooks.sh; source of truth in the
# repo at homelab/hosts/opti/bin/.
#
# 2026-08-20: DIR repointed to the live ZFS pool — the old dev-disk-by-uuid path
# was the pre-migration (2026-07-25) disk, so the LLM had been reading week-old
# runbook copies ever since. If the pool moves again, this breaks again: keep it
# pointed at the path the repo actually lives on.
set -euo pipefail
DIR="/srv/red/fs/ptm/repo/ptm4/homelab/agentic/runbooks"
python3 -c "
import json, os, glob
out = []
for p in sorted(glob.glob(os.path.join('$DIR', '*.md'))):
    # 07 is ~4k tokens of meta-docs about the LLM itself — excluded from the
    # phone feed 2026-08-20 to cut prefill latency ~40%. Still in the repo for
    # humans/Claude; delete these two lines to re-include it.
    if os.path.basename(p) == '07-llm-troubleshooting.md':
        continue
    with open(p) as f:
        out.append({'name': os.path.basename(p), 'content': f.read()})
print(json.dumps(out))
"
