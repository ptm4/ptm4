<script lang="ts">
  import type { Status } from '$lib/types';
  let { status, label = '' }: { status: Status | string; label?: string } = $props();
  const text: Record<string, string> = {
    ok: 'healthy', warn: 'needs attention', crit: 'critical', unknown: 'no fresh data', offline: 'offline',
  };
</script>

<span class="dot {status}" title={label || text[status] || status} role="img" aria-label={label || text[status] || status}></span>
