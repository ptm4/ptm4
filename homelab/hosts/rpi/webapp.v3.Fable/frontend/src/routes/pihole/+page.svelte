<script lang="ts">
  // Pi-hole as a full page: live stats, pause/resume with a duration picker, the
  // top-blocked table with one-click whitelisting, and a jump to the real admin.
  // Everything runs through the backend's session-disciplined proxy — the browser
  // never touches FTL directly, and /allow is allow-only by construction.
  import { ExternalLink } from '@lucide/svelte';
  import { usePihole } from '$lib/api/queries';
  import BlockingCard from './_parts/BlockingCard.svelte';
  import TopBlockedTable from './_parts/TopBlockedTable.svelte';

  const summary = usePihole();
</script>

<div class="pihole-page">
  <div class="board-bar board-head">
    <div class="board-head-text">
      <h2 class="board-title">Pi-hole</h2>
      <div class="board-sub t-dim">
        the LAN's only DNS + DHCP — pausing only lifts blocklist filtering, resolution never stops
      </div>
    </div>
    <span class="spacer"></span>
    <a class="tbtn" href="http://rpi.lan/admin" target="_blank" rel="noreferrer">
      <ExternalLink size={14} aria-hidden="true" /> Admin UI
    </a>
  </div>

  {#if summary.isError}
    <div class="card t-crit">Cannot reach /api/pihole/summary{summary.error ? ` — ${(summary.error as Error).message}` : ''}. Is the backend running?</div>
  {/if}
  {#if summary.isLoading}<div class="spin"></div>{/if}

  <div class="pihole-grid">
    <BlockingCard data={summary.data} />
    <TopBlockedTable />
  </div>
</div>
