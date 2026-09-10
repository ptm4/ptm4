<script lang="ts">
  // Logs — Dozzle, same-origin via nginx /dozzle, with a container picker on top:
  // Dozzle's own event stream gives us container ids, so a pick deep-links straight to
  // /dozzle/container/<id> instead of making you hunt in its sidebar.
  import { page } from '$app/state';
  import { createDozzle } from '$lib/dozzle.svelte';
  import { useContainers } from '$lib/api/queries';

  const dz = createDozzle();
  const containers = useContainers();
  let host = $state('');
  let pick = $state(page.url.searchParams.get('c') ?? '');
  let search = $state('');

  let rows = $derived((containers.data?.hosts ?? []).flatMap((h) => h.containers.map((c) => ({ ...c, host: h.host })))
    .filter((c) => (!host || c.host === host) && (!search || c.name.includes(search))));
  let hosts = $derived([...new Set((containers.data?.hosts ?? []).map((h) => h.host))]);
  let src = $derived.by(() => {
    const id = pick ? dz.byName[pick]?.id : null;
    return id ? `/dozzle/container/${id}` : '/dozzle/';
  });
</script>

<div class="logs">
  <div class="bar">
    <select class="input" bind:value={host}><option value="">all hosts</option>{#each hosts as h (h)}<option value={h}>{h}</option>{/each}</select>
    <input class="input" placeholder="filter containers" bind:value={search} />
    <select class="input wide" bind:value={pick}>
      <option value="">— Dozzle overview —</option>
      {#each rows as c (c.host + '/' + c.name)}<option value={c.name}>{c.name} · {c.host}{c.up ? '' : ' (down)'}</option>{/each}
    </select>
    <span class="faint num">{dz.live ? 'dozzle live' : 'dozzle stream not connected'}{pick && !dz.byName[pick] ? ' · id unknown, showing overview' : ''}</span>
    <a class="tbtn sm" href={src} target="_blank" rel="noreferrer">Open in tab</a>
  </div>
  <div class="frame">
    <iframe {src} title="Dozzle — container logs"></iframe>
  </div>
</div>

<style>
  .logs { display: flex; flex-direction: column; gap: 8px; height: calc(100vh - 100px); }
  .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .bar .input { font-size: 12px; padding: 4px 8px; }
  .bar .wide { min-width: 240px; }
  .frame { flex: 1; min-height: 0; border: 1px solid var(--border); border-radius: var(--r); overflow: hidden; background: var(--bg-inset); }
  .frame iframe { width: 100%; height: 100%; border: 0; display: block; }
  @media (max-width: 860px) { .logs { height: calc(100vh - 150px); } }
</style>
