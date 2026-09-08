<script lang="ts">
  // Fleet-wide command bar for the Control center: cross-host actions, the Kuma
  // monitor summary, and any alert rules currently firing. Self-contained — it
  // owns its own queries, actions and toasts — so the page just drops it in.
  // `useRules()` retries 0 and 404s cleanly on a v2 backend; that renders nothing
  // here, never an error banner.
  import { useQueryClient } from '@tanstack/svelte-query';
  import { RefreshCw, Stethoscope, Pause, TriangleAlert } from '@lucide/svelte';
  import { post } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';
  import { useUptime } from '$lib/api/queries';
  import { useUpdates } from '$lib/api/fleet';
  import { useRules } from '$lib/api/rules';

  const qc = useQueryClient();
  const uptime = useUptime();
  const updatesQ = useUpdates();
  const rules = useRules();

  async function runDoctor() {
    try {
      await post('/api/runners/homelab-doctor/run');
      toast('Homelab Doctor queued', 'ok');
    } catch (e) { toast(`Doctor run failed: ${(e as Error).message}`, 'crit'); }
  }

  async function syncAgents() {
    try {
      await post('/api/agents/sync-all', undefined, 30_000);
      toast('Agents synced', 'ok');
      qc.invalidateQueries({ queryKey: ['agents'] });
    } catch (e) { toast(`Sync failed: ${(e as Error).message}`, 'crit'); }
  }

  async function pausePihole() {
    try {
      await post('/api/pihole/blocking', { enabled: false, seconds: 300 }, 15_000);
      toast('Pi-hole paused for 5 minutes', 'ok');
      qc.invalidateQueries({ queryKey: ['pihole'] });
    } catch (e) { toast(`Pi-hole: ${(e as Error).message}`, 'crit'); }
  }

  let updateCount = $derived((updatesQ.data?.counts.images ?? 0) + (updatesQ.data?.counts.packages ?? 0));

  let sortedMonitors = $derived.by(() => {
    const list = uptime.data?.monitors ?? [];
    // Down/pending first, so a problem is the first thing on the panel.
    const rank: Record<string, number> = { down: 0, pending: 1, maintenance: 2, up: 3 };
    return [...list].sort((a, b) => (rank[a.status] ?? 4) - (rank[b.status] ?? 4) || a.name.localeCompare(b.name));
  });
</script>

<div class="board-bar">
  <span class="spacer"></span>
  <button type="button" class="tb-btn" onclick={runDoctor} title="POST /api/runners/homelab-doctor/run">
    <Stethoscope size={14} aria-hidden="true" /> Doctor
  </button>
  <button type="button" class="tb-btn" onclick={syncAgents} title="POST /api/agents/sync-all">
    <RefreshCw size={14} aria-hidden="true" /> Sync agents
  </button>
  <button type="button" class="tb-btn" onclick={pausePihole} title="POST /api/pihole/blocking (5 min)">
    <Pause size={14} aria-hidden="true" /> Pi-hole 5 min
  </button>
  {#if updateCount > 0}
    <a class="tb-btn" href="/updates">⬆ {updateCount} update{updateCount > 1 ? 's' : ''}</a>
  {/if}
</div>

{#if rules.data?.hits && rules.data.hits.length > 0}
  <section class="glass card ck-rules">
    <div class="w-head">
      <span class="w-title"><TriangleAlert size={12} aria-hidden="true" style="vertical-align: -2px" /> Firing now</span>
      <span class="w-meta"><a href="/incidents">All incidents →</a></span>
    </div>
    <div class="rows">
      {#each rules.data.hits as h (h.key)}
        <a class="row" href="/incidents">
          <span class="pip" data-s={h.severity === 'critical' ? 'crit' : 'warn'}></span>
          <span class="who">{h.host ?? 'fleet'}</span>
          <span class="what">{h.message}</span>
          <span class="num faint">{h.since}</span>
        </a>
      {/each}
    </div>
  </section>
{/if}

<section class="glass card ck-monitors">
  <div class="w-head">
    <span class="w-title">Monitors</span>
    <span class="w-meta">
      <a href="http://rpi.lan:3001/" target="_blank" rel="noreferrer">Uptime Kuma</a>
    </span>
  </div>
  {#if uptime.data?.ok}
    <span class="pill" data-s={uptime.data.down ? 'crit' : uptime.data.pending ? 'warn' : 'ok'}>
      {uptime.data.up}/{uptime.data.total} up{uptime.data.down ? ` · ${uptime.data.down} down` : ''}{uptime.data.pending ? ` · ${uptime.data.pending} pending` : ''}
    </span>
    <div class="mon-grid">
      {#each sortedMonitors as m (m.name)}
        <span class="mon" title={`${m.name} — ${m.status}${m.ms != null ? `, ${m.ms}ms` : ''}`}>
          <span class="cdot" data-s={m.status === 'up' ? 'ok' : m.status === 'down' ? 'crit' : 'warn'}></span>
          {m.name}
          {#if m.ms != null}<span class="t-dim"> {m.ms}ms</span>{/if}
        </span>
      {/each}
    </div>
  {:else}
    <div class="t-dim">Unavailable.</div>
  {/if}
</section>

<style>
  .ck-rules .row { text-decoration: none; color: inherit; }
  .ck-rules .row:hover .what { color: var(--accent); }
</style>
