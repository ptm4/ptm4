#!/bin/bash
# Forced SSH command (see ~/.ssh/authorized_keys) for the phone's read-only key.
# Dumps opti's auto-generated homelab docs as a JSON array of {name, content}, so
# the phone's local LLM can read them live over SSH with no local sync/copy needed.
# Deployed at opti:~/bin/dump-docs.sh; source of truth in the repo at
# homelab/hosts/opti/bin/.
#
# 2026-08-20: DIR repointed to the live ZFS pool — /srv/pool died with the
# 2026-07-25 migration and this script silently returned [] ever since (the LLM
# lost all generated host docs and nothing errored). Must match OUT dir of
# homelab/tools/collectors/docs-generator.py.
set -euo pipefail
DIR="/srv/red/fs/ptm/agent-logs/generated-docs"
python3 -c "
import json, os, glob
# Whitelist (2026-08-20): the full doc set overflows the phone's 13312-token
# context (14993 tokens measured -> every ask 400s). Overview/network/software
# carry the ask-value; hardware/security are audit detail (and security output
# doesn't belong in a no-auth LLM's context). Keep total feed under ~34KB.
KEEP = {'20-overview.md', '21-network.md', '23-software.md'}
out = []
for p in sorted(glob.glob(os.path.join('$DIR', '*.md'))):
    if os.path.basename(p) not in KEEP:
        continue
    with open(p) as f:
        out.append({'name': os.path.basename(p), 'content': f.read()})
print(json.dumps(out))
"
