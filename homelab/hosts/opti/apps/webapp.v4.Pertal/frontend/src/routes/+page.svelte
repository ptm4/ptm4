<script lang="ts">
  import StatusDot from '$lib/components/StatusDot.svelte';
  import Age from '$lib/components/Age.svelte';
  import TodayStrip from '$lib/components/TodayStrip.svelte';
  import { BellOff, Bell } from '@lucide/svelte';
  import { live } from '$lib/live.svelte';
  import { actions } from '$lib/actions.svelte';
  import { pct, uptime, tone, ago } from '$lib/format';
  import type { Issue, Resource } from '$lib/types';

  const hosts = $derived(live.resources.filter((r) => r.type === 'host'));
  const s = $derived(live.summary);
  const servers = $derived(hosts.filter((h) => h.id !== 'android'));
  const serversUp = $derived(servers.filter((h) => h.online === true).length);
  const headline = $derived(
    !live.loaded ? (live.error ? 'No data — opti is unreachable' : 'Loading…')
      : serversUp === servers.length ? `All ${servers.length} servers up`
      : `${serversUp} of ${servers.length} servers up`,
  );
  const sources = $derived(Object.values(live.snapshots).sort((a, b) => a.key.localeCompare(b.key)));
  const failing = $derived(sources.filter((m) => m.ok === false));
  const recent = $derived(live.activity.slice(0, 8));

  let open = $state<Record<string, boolean>>({});
  // Clicked, waiting for the rebuild to move the row. Cleared if the job couldn't start.
  let busy = $state<Record<string, boolean>>({});
  async function ack(i: Issue, on: boolean) {
    busy[i.key] = true;
    if (!(await actions.ack(i.key, `${i.resource}: ${i.text}`, on))) busy[i.key] = false;
  }
  const childCount = (h: Resource) => h.counts ? `${h.counts.running}/${h.counts.containers}` : '—';
</script>

<svelte:head><title>Status · Pertal</title></svelte:head>

<section class="hero">
  <div>
    <h1>{headline}</h1>
    <p class="muted">
      {#if s}
        {#if s.counts.crit}<span class="crit">{s.counts.crit} critical</span> · {/if}
        {#if s.counts.warn}{s.counts.warn} to look at · {/if}
        {s.containers.running}/{s.containers.total} containers running
        {#if s.hosts.offline} · android offline (normal){/if}
      {/if}
    </p>
  </div>
  <Age at={live.builtAt} prefix="updated " staleAfterMs={60_000} />
</section>

<section class="hosts">
  {#each hosts as h (h.id)}
    <a class="panel host" href="/r/{h.id}" data-status={h.status}>
      <div class="host-head">
        <StatusDot status={h.status} />
        <strong>{h.name}</strong>
        <span class="faint role">{h.facts.find((f) => f.label === 'Role')?.value}</span>
      </div>
      <div class="state" class:attn={h.status === 'warn' || h.status === 'crit'}>{h.status_text}</div>
      {#if h.metrics}
        <div class="meters">
          <div><span class="faint">CPU</span><span class="num">{pct(h.metrics.cpu_pct)}</span><div class="meter {tone(h.metrics.cpu_pct)}"><span style="width:{h.metrics.cpu_pct ?? 0}%"></span></div></div>
          <div><span class="faint">Mem</span><span class="num">{pct(h.metrics.mem_pct)}</span><div class="meter {tone(h.metrics.mem_pct)}"><span style="width:{h.metrics.mem_pct ?? 0}%"></span></div></div>
          <div><span class="faint">Temp</span><span class="num">{h.metrics.temp_c != null ? `${Math.round(h.metrics.temp_c)}°` : '—'}</span></div>
          <div><span class="faint">Ctr</span><span class="num">{childCount(h)}</span></div>
        </div>
        <div class="foot faint"><span>up {uptime(h.metrics.uptime_s)}</span><Age at={h.updated_at} staleAfterMs={45_000} /></div>
      {:else}
        <div class="foot faint"><span>{h.state_text}</span><Age at={h.updated_at} /></div>
      {/if}
    </a>
  {/each}
</section>

<TodayStrip />

<div class="cols">
  <section class="panel">
    <div class="panel-head"><h2>Needs attention</h2><span class="faint">{s?.issues.length ?? 0}</span></div>
    <div class="rows">
      {#each s?.issues ?? [] as i (i.key)}
        <div class="row issue">
          <span class="badge {i.severity}">{i.severity === 'crit' ? 'critical' : 'warn'}</span>
          <div class="issue-main">
            <div>
              {#if i.resource_id}<a href="/r/{i.resource_id}">{i.resource}</a>{:else}<span class="muted">{i.resource}</span>{/if}
              <span class="issue-text">{i.text}</span>
            </div>
            {#if i.details}
              <button class="linkish" onclick={() => (open[i.key] = !open[i.key])}>
                {open[i.key] ? 'hide' : 'show'} {i.details.length}
              </button>
              {#if open[i.key]}
                <ul class="details">{#each i.details as d}<li>{d}</li>{/each}</ul>
              {/if}
            {/if}
          </div>
          <span class="faint when">{i.at ? ago(i.at, live.now) : ''}</span>
          <button class="btn ghost icon ackbtn" disabled={busy[i.key]} onclick={() => ack(i, true)}
            title="Acknowledge — I know. Hidden until it gets more severe or something new appears; numbers changing won't bring it back."
            aria-label="Acknowledge {i.resource}: {i.text}"><BellOff size={14} /></button>
        </div>
      {:else}
        <div class="empty">{live.loaded ? 'Nothing needs you.' : 'Loading…'}</div>
      {/each}
    </div>
    {#if s?.acknowledged?.length}
      <details class="acked">
        <summary><BellOff size={13} /> {s.acknowledged.length} acknowledged</summary>
        <div class="rows">
          {#each s.acknowledged as i (i.key)}
            <div class="row issue">
              <span class="badge">{i.severity === 'crit' ? 'critical' : 'warn'}</span>
              <div class="issue-main">
                <div>
                  {#if i.resource_id}<a href="/r/{i.resource_id}">{i.resource}</a>{:else}<span class="muted">{i.resource}</span>{/if}
                  <span class="issue-text">{i.text}</span>
                </div>
                <div class="faint small">acknowledged {ago(i.acked?.at, live.now)}{#if i.acked?.note} · {i.acked.note}{/if}</div>
              </div>
              <span></span>
              <button class="btn ghost icon ackbtn" disabled={busy[i.key]} onclick={() => ack(i, false)}
                title="Un-acknowledge — show it in Needs attention again" aria-label="Un-acknowledge {i.resource}: {i.text}"><Bell size={14} /></button>
            </div>
          {/each}
        </div>
      </details>
    {/if}
  </section>

  <div class="side">
    <section class="panel">
      <div class="panel-head"><h2>Recent activity</h2><a href="/activity" class="faint">all</a></div>
      <div class="rows">
        {#each recent as a (a.id)}
          <div class="row act">
            <span class="dot {a.severity === 'ok' ? 'ok' : a.severity}"></span>
            {#if a.resource_id}<a href="/r/{a.resource_id}" class="act-text">{a.text}</a>{:else}<span class="act-text">{a.text}</span>{/if}
            <span class="faint when">{ago(a.at, live.now)}</span>
          </div>
        {:else}
          <div class="empty">Quiet so far. Changes appear here as they happen.</div>
        {/each}
      </div>
    </section>

    <section class="panel">
      <div class="panel-head"><h2>Data sources</h2><span class="faint">{sources.length - failing.length}/{sources.length} ok</span></div>
      <div class="chips">
        {#each sources as m (m.key)}
          <span class="chip" class:bad={m.ok === false} title={m.ok === false ? m.error : `${m.label}: every ${Math.round(m.interval_ms / 1000)}s, took ${m.took_ms} ms`}>
            {m.key}<Age at={m.fetched_at} staleAfterMs={m.stale_after_ms} />
          </span>
        {/each}
      </div>
    </section>
  </div>
</div>

<style>
  .hero { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--s4); margin-bottom: var(--s4); }
  .hero p { margin: 4px 0 0; }
  .crit { color: var(--crit); font-weight: 600; }

  .hosts { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: var(--s3); margin-bottom: var(--s4); }
  .host { display: flex; flex-direction: column; gap: 8px; padding: var(--s3) var(--s4); color: var(--ink); text-decoration: none; }
  .host:hover { border-color: var(--border-2); text-decoration: none; }
  .host[data-status='crit'] { border-color: color-mix(in srgb, var(--crit) 45%, var(--border)); }
  .host-head { display: flex; align-items: center; gap: 8px; }
  .role { margin-left: auto; font-size: var(--fs-xs); }
  .state { font-size: var(--fs-sm); color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .state.attn { color: var(--warn); }
  .host[data-status='crit'] .state.attn { color: var(--crit); }
  .meters { display: grid; grid-template-columns: 1fr 1fr auto auto; gap: 10px; align-items: end; }
  .meters > div { display: grid; grid-template-columns: auto 1fr; gap: 2px 6px; font-size: var(--fs-sm); }
  .meters .meter { grid-column: 1 / -1; }
  .foot { display: flex; justify-content: space-between; font-size: var(--fs-xs); }

  .cols { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); gap: var(--s3); align-items: start; }
  .side { display: flex; flex-direction: column; gap: var(--s3); }
  .issue { grid-template-columns: auto minmax(0, 1fr) auto auto; align-items: start; }
  .ackbtn { margin: -4px -6px -4px 0; color: var(--ink-3); }
  .ackbtn:hover { color: var(--ink); }
  .acked { border-top: 1px solid var(--border); }
  .acked summary { display: flex; align-items: center; gap: 6px; padding: 8px var(--s4); cursor: pointer; color: var(--ink-3); font-size: var(--fs-xs); list-style: none; }
  .acked summary::-webkit-details-marker { display: none; }
  .acked summary:hover { color: var(--ink-2); }
  .acked .issue { opacity: .7; }
  .small { font-size: var(--fs-xs); margin-top: 2px; }
  .issue-main { min-width: 0; font-size: var(--fs-sm); }
  .issue-text { margin-left: 6px; color: var(--ink-2); }
  .when { font-size: var(--fs-xs); white-space: nowrap; }
  .details { margin: 6px 0 0; padding-left: 18px; color: var(--ink-3); font-size: var(--fs-xs); }
  .linkish { border: 0; background: none; padding: 0; margin-top: 2px; color: var(--accent); cursor: pointer; font-size: var(--fs-xs); }
  .act { grid-template-columns: auto minmax(0, 1fr) auto; font-size: var(--fs-sm); }
  .act-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink-2); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; padding: var(--s3) var(--s4); }
  .chip {
    display: inline-flex; align-items: center; gap: 6px; padding: 2px 8px;
    border: 1px solid var(--border); border-radius: 999px; font: var(--fs-xs) var(--mono); color: var(--ink-2);
  }
  .chip.bad { border-color: var(--warn); color: var(--warn); }

  @media (max-width: 900px) {
    .cols { grid-template-columns: minmax(0, 1fr); }
    .hero { flex-direction: column; align-items: flex-start; }
  }
</style>
