<script lang="ts">
  // Latest collector run per host (homelab-db): doctor, hardware, software, network.
  import { onMount } from 'svelte';
  import Age from '$lib/components/Age.svelte';
  import { api } from '$lib/api';
  import { live } from '$lib/live.svelte';
  import { ago } from '$lib/format';

  type Report = { tool: string; run_at: string; status: string; summary: string };
  let data = $state<{ hosts: Record<string, { reports: Report[]; error?: string }>; doctor: any; services: any[]; fetched_at: string | null; error: string | null } | null>(null);
  let err = $state<string | null>(null);

  async function load() {
    try { data = await api.reports(); err = null; } catch (e) { err = (e as Error).message; }
  }
  onMount(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  });

  const toolLabel: Record<string, string> = {
    'homelab-doctor': 'Doctor', 'hardware-report': 'Hardware', 'software-inventory': 'Software', 'network-report': 'Network',
  };
  const tone = (s: string) => (s === 'critical' || s === 'crit' ? 'crit' : s === 'warn' ? 'warn' : '');
</script>

<svelte:head><title>Reports · Pertal</title></svelte:head>

<div class="head">
  <h1>Reports</h1>
  <span class="faint">from homelab-db · <Age at={data?.fetched_at} staleAfterMs={20 * 60_000} /></span>
</div>
{#if err || data?.error}<p class="empty">{err || data?.error}</p>{/if}

{#if data?.doctor}
  <section class="panel doctor">
    <div class="panel-head"><h2>Doctor</h2><span class="badge {tone(data.doctor.status)}">{data.doctor.status}</span><span class="faint">{ago(data.doctor.run_at, live.now)}</span></div>
    <div class="panel-body">
      <p class="muted">{data.doctor.summary}</p>
      <div class="services">
        {#each data.services as s (s.name)}
          <span class="svc"><span class="dot {s.up ? '' : 'crit'}"></span>{s.name}{#if s.cert_days_left != null}<span class="faint"> · cert {s.cert_days_left} d</span>{/if}</span>
        {/each}
      </div>
    </div>
  </section>
{/if}

<div class="hosts">
  {#each Object.entries(data?.hosts ?? {}) as [host, h] (host)}
    <section class="panel">
      <div class="panel-head"><h2><a href="/r/{host}">{host}</a></h2>{#if h.error}<span class="badge warn">{h.error}</span>{/if}</div>
      <div class="rows">
        {#each h.reports as r (r.tool)}
          <div class="row rep">
            <span class="tool">{toolLabel[r.tool] ?? r.tool}</span>
            <span class="badge {tone(r.status)}">{r.status}</span>
            <span class="sum muted">{r.summary}</span>
            <span class="faint when">{ago(r.run_at, live.now)}</span>
          </div>
        {:else}
          <div class="empty">No reports.</div>
        {/each}
      </div>
    </section>
  {/each}
</div>

<style>
  .head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--s3); flex-wrap: wrap; margin-bottom: var(--s3); }
  .doctor { margin-bottom: var(--s3); }
  .doctor p { margin: 0 0 var(--s2); }
  .services { display: flex; flex-wrap: wrap; gap: var(--s3); font-size: var(--fs-sm); }
  .svc { display: inline-flex; align-items: center; gap: 6px; }
  .hosts { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: var(--s3); }
  .rep { grid-template-columns: 76px auto minmax(0, 1fr) auto; font-size: var(--fs-sm); align-items: start; }
  .tool { font-weight: 600; }
  .sum { overflow-wrap: anywhere; }
  .when { font-size: var(--fs-xs); white-space: nowrap; }
  @media (max-width: 720px) {
    .hosts { grid-template-columns: minmax(0, 1fr); }
    .rep { grid-template-columns: auto auto minmax(0, 1fr); }
    .rep .sum { grid-column: 1 / -1; }
  }
</style>
