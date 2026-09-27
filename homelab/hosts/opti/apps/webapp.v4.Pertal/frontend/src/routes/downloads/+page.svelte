<script lang="ts">
  // Downloads: drop a .torrent (or paste a magnet), watch it in the queue; when it
  // finishes, noblenumbat's media-import timer moves it to opti › ptm/Downloads.
  // Every add/pause/resume/delete is a job — it shows in the tray and the Activity log.
  import { FileUp, Pause, Play, Trash2, Shield, ShieldAlert, ArrowDown, ArrowUp } from '@lucide/svelte';
  import Age from '$lib/components/Age.svelte';
  import { api } from '$lib/api';
  import { actions } from '$lib/actions.svelte';
  import { live } from '$lib/live.svelte';
  import { bytes, rate } from '$lib/format';

  let data = $state<any>(null);
  let err = $state<string | null>(null);
  let files = $state<File[]>([]);
  let urls = $state('');
  let dragging = $state(false);
  let adding = $state(false);
  let filter = $state<'all' | 'pertal' | 'active' | 'done'>('all');
  let input = $state<HTMLInputElement>();

  async function load() {
    try { data = await api.downloads.get(); err = null; } catch (e) { err = (e as Error).message; }
  }
  const stamp = $derived(['qbt:queue', 'vpn:gluetun'].map((k) => live.snapshots[k]?.fetched_at).join());
  $effect(() => { void stamp; void load(); });

  function takeFiles(list: FileList | null) {
    const picked = [...(list ?? [])].filter((f) => f.name.toLowerCase().endsWith('.torrent'));
    files = [...files, ...picked].slice(0, 20);
  }
  async function add() {
    if (!files.length && !urls.trim()) return;
    adding = true;
    try {
      const { job } = await api.downloads.add(files, urls);
      actions.track(job);
      files = []; urls = '';
    } catch (e) {
      actions.fail('Add torrents', e);
    } finally { adding = false; }
  }
  async function op(t: any, what: 'pause' | 'resume') {
    try { actions.track((await api.downloads.op(t.hash, what)).job); } catch (e) { actions.fail(`${what} ${t.name}`, e); }
  }
  function remove(t: any, deleteFiles: boolean) {
    actions.ask({
      title: deleteFiles ? `Delete ${t.name} and its files?` : `Remove ${t.name} from the queue?`,
      body: deleteFiles ? 'The downloaded data is deleted from noblenumbat too. This cannot be undone.' : 'The files stay where they are; only the torrent is removed.',
      label: deleteFiles ? 'Delete with files' : 'Remove',
      run: async () => {
        try { actions.track((await api.downloads.op(t.hash, 'delete', { confirm: true, deleteFiles })).job); } catch (e) { actions.fail(`Delete ${t.name}`, e); }
      },
    });
  }

  const torrents = $derived<any[]>(data?.queue?.torrents ?? []);
  const DONE = ['uploading', 'stalledUP', 'pausedUP', 'queuedUP', 'forcedUP', 'checkingUP'];
  const shown = $derived(torrents.filter((t) =>
    filter === 'all' ? true : filter === 'pertal' ? t.category === data?.category : filter === 'done' ? t.progress >= 1 : t.progress < 1));
  const eta = (s: number) => (s >= 8640000 ? '∞' : s >= 86400 ? `${Math.round(s / 86400)}d` : s >= 3600 ? `${Math.round(s / 3600)}h` : s >= 60 ? `${Math.round(s / 60)}m` : `${s}s`);
  const stateText = (t: any) =>
    t.progress >= 1 ? (t.category === data?.category ? 'done — moving to opti' : 'seeding')
    : t.state === 'metaDL' ? 'fetching metadata' : t.state.startsWith('paused') ? 'paused'
    : t.state === 'stalledDL' ? 'stalled' : t.state === 'queuedDL' ? 'queued' : 'downloading';
  const paused = (t: any) => t.state.startsWith('paused');
</script>

<svelte:head><title>Downloads · Pertal</title></svelte:head>

<div class="head">
  <h1>Downloads</h1>
  {#if data?.dry}<span class="badge warn">dry run — nothing is sent to qBittorrent</span>{/if}
</div>
{#if err}<p class="banner">{err}</p>{/if}

<section class="stats">
  <div class="panel stat">
    {#if data?.vpn}
      <div class="row1">{#if data.vpn.forwarded_port}<Shield size={16} />{:else}<ShieldAlert size={16} class="warnico" />{/if}<strong>VPN</strong><span class="faint">{data.vpn.org ?? ''}</span></div>
      <div class="big">{data.vpn.city ?? '—'}, {data.vpn.country ?? '—'}</div>
      <div class="faint small">{data.vpn.public_ip} · {#if data.vpn.forwarded_port}port {data.vpn.forwarded_port} open{:else}<span class="warn">no forwarded port — fewer peers</span>{/if}</div>
    {:else}
      <div class="row1"><ShieldAlert size={16} class="warnico" /><strong>VPN</strong></div>
      <div class="faint small">{data?.vpn_meta?.error ?? 'Loading…'}</div>
    {/if}
  </div>
  <div class="panel stat">
    <div class="row1"><strong>Transfer</strong><span class="faint">{data?.queue?.transfer?.status ?? ''}</span></div>
    <div class="big"><ArrowDown size={16} /> {rate(data?.queue?.transfer?.dl_speed)} <span class="sep"></span><ArrowUp size={16} /> {rate(data?.queue?.transfer?.up_speed)}</div>
    <div class="faint small">{torrents.length} torrent(s) · <Age at={data?.queue_meta?.fetched_at} staleAfterMs={30_000} /></div>
  </div>
</section>

<section class="panel add"
  class:drag={dragging}
  aria-label="Add torrents"
  ondragover={(e) => { e.preventDefault(); dragging = true; }}
  ondragleave={() => (dragging = false)}
  ondrop={(e) => { e.preventDefault(); dragging = false; takeFiles(e.dataTransfer?.files ?? null); }}>
  <button class="drop" onclick={() => input?.click()}>
    <FileUp size={22} />
    <span><strong>Drop .torrent files</strong> or click to choose</span>
    <span class="faint small">Finished downloads land on opti › ptm/Downloads</span>
  </button>
  <input bind:this={input} type="file" accept=".torrent,application/x-bittorrent" multiple hidden onchange={(e) => takeFiles(e.currentTarget.files)} />
  <div class="side">
    <textarea class="field links" rows="2" placeholder="…or paste magnet links (one per line)" bind:value={urls}></textarea>
    {#if files.length}
      <div class="picked">
        {#each files as f, i (f.name + i)}<span class="chip">{f.name}<button aria-label="Remove {f.name}" onclick={() => (files = files.filter((_, j) => j !== i))}>×</button></span>{/each}
      </div>
    {/if}
    <button class="btn primary" disabled={adding || (!files.length && !urls.trim())} onclick={add}>
      {adding ? 'Adding…' : `Add ${files.length + (urls.trim() ? urls.trim().split(/\s+/).length : 0) || ''} to qBittorrent`}
    </button>
  </div>
</section>

<section class="panel">
  <div class="panel-head">
    <h2>Queue</h2>
    <div class="seg" role="group" aria-label="Filter">
      {#each [['all', 'All'], ['active', 'Downloading'], ['done', 'Done'], ['pertal', 'Added here']] as [id, label]}
        <button aria-pressed={filter === id} onclick={() => (filter = id as typeof filter)}>{label}</button>
      {/each}
    </div>
  </div>
  <div class="rows">
    {#each shown as t (t.hash)}
      <div class="row tor">
        <div class="main">
          <div class="name">{t.name}{#if t.category}<span class="badge {t.category === data?.category ? 'accent' : ''}">{t.category}</span>{/if}</div>
          <div class="meter" class:warn={t.state === 'stalledDL'}><span style="width:{Math.round(t.progress * 100)}%"></span></div>
          <div class="faint small">
            {Math.round(t.progress * 100)}% of {bytes(t.size)} · {stateText(t)}
            {#if t.progress < 1 && !paused(t)} · ↓ {rate(t.dlspeed)} · {eta(t.eta)} left{/if}
            {#if t.upspeed > 0} · ↑ {rate(t.upspeed)}{/if}
            · {t.seeds} seeds
          </div>
        </div>
        <div class="acts">
          {#if paused(t)}
            <button class="btn icon" aria-label="Resume" title="Resume" onclick={() => op(t, 'resume')}><Play size={14} /></button>
          {:else}
            <button class="btn icon" aria-label="Pause" title="Pause" onclick={() => op(t, 'pause')}><Pause size={14} /></button>
          {/if}
          <button class="btn icon danger" aria-label="Remove" title="Remove (keep files)" onclick={() => remove(t, false)}><Trash2 size={14} /></button>
          <button class="btn danger small" title="Delete torrent and its files" onclick={() => remove(t, true)}>+ files</button>
        </div>
      </div>
    {:else}
      <div class="empty">{data ? 'Nothing in the queue.' : 'Loading…'}</div>
    {/each}
  </div>
</section>

<style>
  .head { display: flex; align-items: center; gap: var(--s3); margin-bottom: var(--s3); flex-wrap: wrap; }
  .banner { padding: 8px 12px; border: 1px solid var(--warn); border-radius: var(--r); background: var(--warn-dim); color: var(--warn); font-size: var(--fs-sm); }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: var(--s3); margin-bottom: var(--s3); }
  .stat { padding: var(--s3) var(--s4); display: flex; flex-direction: column; gap: 4px; }
  .row1 { display: flex; align-items: center; gap: 8px; font-size: var(--fs-sm); }
  .row1 .faint { margin-left: auto; }
  :global(.warnico) { color: var(--warn); }
  .big { display: flex; align-items: center; gap: 6px; font-size: var(--fs-lg); font-weight: 600; }
  .sep { width: 12px; }
  .small { font-size: var(--fs-xs); }
  .warn { color: var(--warn); }
  .add { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--s3); padding: var(--s3); margin-bottom: var(--s3); }
  .add.drag { border-color: var(--accent); background: var(--accent-dim); }
  .drop {
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; min-height: 110px;
    border: 1.5px dashed var(--border-2); border-radius: var(--r); background: var(--bg-inset); cursor: pointer; color: var(--ink-2);
  }
  .drop:hover { border-color: var(--accent); color: var(--ink); }
  .side { display: flex; flex-direction: column; gap: 8px; }
  .links { height: auto; min-height: 60px; padding: 8px 10px; resize: vertical; font: var(--fs-sm) var(--mono); }
  .picked { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { display: inline-flex; align-items: center; gap: 4px; padding: 2px 4px 2px 8px; border-radius: 999px; background: var(--surface-2); border: 1px solid var(--border); font-size: var(--fs-xs); }
  .chip button { border: 0; background: none; cursor: pointer; color: var(--ink-3); font-size: 14px; line-height: 1; }
  .tor { grid-template-columns: minmax(0, 1fr) auto; }
  .main { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .name { display: flex; align-items: center; gap: 8px; font-size: var(--fs-sm); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .acts { display: flex; gap: 4px; }
  .btn.small { height: 30px; font-size: var(--fs-xs); }
  @media (max-width: 720px) {
    .add { grid-template-columns: minmax(0, 1fr); }
    .tor { grid-template-columns: minmax(0, 1fr); }
  }
</style>
