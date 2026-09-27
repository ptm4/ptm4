<script lang="ts">
  // Requests: Seerr's queue with approve / decline (both jobs). Asking for something new
  // happens in Seerr itself — it owns search, seasons and quotas.
  import { ExternalLink, Check, X, Film, Tv } from '@lucide/svelte';
  import Age from '$lib/components/Age.svelte';
  import { ApiError } from '$lib/api';
  import { actions } from '$lib/actions.svelte';
  import { live } from '$lib/live.svelte';
  import { ago } from '$lib/format';

  let d = $state<any>(null);
  let err = $state<string | null>(null);
  async function load() {
    try {
      const res = await fetch('/api/requests', { signal: AbortSignal.timeout(8000) });
      if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
      d = await res.json(); err = null;
    } catch (e) { err = (e as Error).message; }
  }
  const stamp = $derived(live.snapshots['seerr:requests']?.fetched_at);
  $effect(() => { void stamp; void load(); });

  async function decide(r: any, op: 'approve' | 'decline') {
    try {
      const res = await fetch(`/api/requests/${r.id}/${op}`, { method: 'POST' });
      const body = await res.json();
      if (!res.ok) throw new ApiError(res.status, body.error);
      actions.track(body.job);
    } catch (e) { actions.fail(`${op} ${r.title}`, e); }
  }

  const counts = $derived(d?.data?.counts ?? {});
  const tone = (s: string) => (s === 'pending' ? 'warn' : s === 'declined' || s === 'failed' ? 'crit' : s === 'available' ? 'info' : '');
</script>

<svelte:head><title>Requests · Pertal</title></svelte:head>

<div class="head">
  <h1>Requests</h1>
  <a class="btn primary" href={d?.seerr_url ?? 'http://opti.lan:5055'} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Request something in Seerr</a>
</div>
{#if err}<p class="banner">{err}</p>{/if}

{#if d && !d.configured}
  <section class="panel setup">
    <div class="panel-head"><h2>Finish setting up Seerr</h2></div>
    <ol class="panel-body">
      <li>Open <a href="http://opti.lan:5055" target="_blank" rel="noreferrer">Seerr on opti.lan:5055</a> and choose <strong>Jellyfin</strong>.</li>
      <li>Jellyfin URL <code>http://192.168.1.6:8096</code>, sign in with your Jellyfin admin account, pick the libraries.</li>
      <li>Add <strong>Radarr</strong> <code>http://192.168.1.6:7878</code> and <strong>Sonarr</strong> <code>http://192.168.1.6:8989</code> with their API keys (Settings → General in each).</li>
      <li>In Seerr: Settings → General → copy the <strong>API key</strong>, add <code>SEERR_API_KEY=…</code> to <code>/srv/docker/compose/.env</code> on opti, and push (or restart the pertal container).</li>
    </ol>
  </section>
{:else if d?.meta?.ok === false && !d?.data}
  <p class="banner">Seerr is not answering: {d.meta.error}</p>
{:else if d?.data}
  <section class="counts">
    {#each [['pending', 'Waiting for you'], ['approved', 'Approved'], ['processing', 'Downloading'], ['available', 'Available']] as [k, label]}
      <div class="panel count"><span class="faint">{label}</span><strong class="num">{counts[k] ?? 0}</strong></div>
    {/each}
  </section>

  <section class="panel">
    <div class="panel-head"><h2>Latest requests</h2><span class="faint"><Age at={d.meta?.fetched_at} staleAfterMs={5 * 60_000} /></span></div>
    <div class="rows">
      {#each d.data.requests as r (r.id)}
        <div class="row req">
          {#if r.poster}<img src={r.poster} alt="" width="40" height="60" loading="lazy" />{:else}<div class="noposter">{#if r.type === 'tv'}<Tv size={18} />{:else}<Film size={18} />{/if}</div>{/if}
          <div class="main">
            <div class="title">{r.title}{#if r.year} <span class="faint">({r.year})</span>{/if}</div>
            <div class="faint small">
              {r.type === 'tv' ? 'Series' : 'Movie'}{#if r.seasons?.length} · seasons {r.seasons.join(', ')}{/if}
              · {r.requested_by} · {ago(r.created_at, live.now)}
            </div>
            <div class="badges">
              <span class="badge {tone(r.status)}">{r.status}</span>
              {#if r.status === 'approved'}<span class="badge {tone(r.media_status)}">{r.media_status}</span>{/if}
            </div>
          </div>
          {#if r.status === 'pending'}
            <div class="acts">
              <button class="btn primary" onclick={() => decide(r, 'approve')}><Check size={14} /> Approve</button>
              <button class="btn danger" onclick={() => decide(r, 'decline')}><X size={14} /> Decline</button>
            </div>
          {/if}
        </div>
      {:else}
        <div class="empty">No requests yet.</div>
      {/each}
    </div>
  </section>
{:else if !err}
  <p class="empty">Loading…</p>
{/if}

<style>
  .head { display: flex; align-items: center; justify-content: space-between; gap: var(--s3); flex-wrap: wrap; margin-bottom: var(--s3); }
  .banner { padding: 8px 12px; border: 1px solid var(--warn); border-radius: var(--r); background: var(--warn-dim); color: var(--warn); font-size: var(--fs-sm); }
  .setup ol { margin: 0; padding: var(--s3) var(--s5); display: flex; flex-direction: column; gap: 8px; font-size: var(--fs-sm); }
  code { font: var(--fs-xs) var(--mono); background: var(--surface-2); padding: 1px 5px; border-radius: 3px; }
  .counts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--s3); margin-bottom: var(--s3); }
  .count { padding: var(--s3) var(--s4); display: flex; flex-direction: column; gap: 2px; font-size: var(--fs-sm); }
  .count strong { font-size: var(--fs-2xl); font-weight: 600; }
  .req { grid-template-columns: 40px minmax(0, 1fr) auto; align-items: start; }
  .req img, .noposter { width: 40px; height: 60px; border-radius: 4px; object-fit: cover; background: var(--surface-2); }
  .noposter { display: grid; place-items: center; color: var(--ink-3); }
  .main { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .title { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .small { font-size: var(--fs-xs); }
  .badges { display: flex; gap: 4px; }
  .acts { display: flex; gap: 6px; }
  @media (max-width: 720px) {
    .counts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .req { grid-template-columns: 40px minmax(0, 1fr); }
    .acts { grid-column: 1 / -1; }
  }
</style>
