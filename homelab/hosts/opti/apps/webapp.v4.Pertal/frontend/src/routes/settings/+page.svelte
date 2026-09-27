<script lang="ts">
  import { theme, type Family, type Mode } from '$lib/theme.svelte';
  import { live } from '$lib/live.svelte';
  import Age from '$lib/components/Age.svelte';
  import { age } from '$lib/format';

  const families: { id: Family; label: string; note: string; swatch: string[] }[] = [
    { id: 'gruvbox', label: 'Gruvbox', note: 'Default — warm retro, hard contrast', swatch: ['#1d2021', '#282828', '#ebdbb2', '#fabd2f', '#83a598', '#fe8019', '#fb4934'] },
    { id: 'github', label: 'GitHub', note: "v3's look — cool navy, blue and purple", swatch: ['#0d1117', '#161b22', '#e6edf3', '#d2a8ff', '#79c0ff', '#ffa657', '#ff7b72'] },
  ];
  const modes: Mode[] = ['dark', 'light', 'system'];
  const sources = $derived(Object.values(live.snapshots).sort((a, b) => a.key.localeCompare(b.key)));
</script>

<svelte:head><title>Settings · Pertal</title></svelte:head>

<h1>Settings</h1>

<section class="panel block">
  <div class="panel-head"><h2>Appearance</h2><span class="faint">saved in this browser</span></div>
  <div class="panel-body">
    <div class="families">
      {#each families as f (f.id)}
        <button class="family" aria-pressed={theme.family === f.id} onclick={() => theme.set(f.id, theme.mode)}>
          <span class="swatch">{#each f.swatch as c}<i style="background:{c}"></i>{/each}</span>
          <strong>{f.label}</strong>
          <span class="faint">{f.note}</span>
        </button>
      {/each}
    </div>
    <div class="mode">
      <span class="muted">Mode</span>
      <div class="seg" role="group" aria-label="Mode">
        {#each modes as m}
          <button aria-pressed={theme.mode === m} onclick={() => theme.set(theme.family, m)}>{m}</button>
        {/each}
      </div>
      {#if theme.mode === 'system'}<span class="faint">following your device: {theme.resolved}</span>{/if}
    </div>
  </div>
</section>

<section class="panel block">
  <div class="panel-head"><h2>Data sources</h2><span class="faint">every card in Pertal reads one of these</span></div>
  <div class="rows">
    <div class="row src header"><span>Source</span><span>Every</span><span>Last read</span><span>Took</span><span>State</span></div>
    {#each sources as m (m.key)}
      <div class="row src">
        <span class="mono">{m.key}</span>
        <span class="num faint">{age(m.interval_ms)}</span>
        <Age at={m.fetched_at} staleAfterMs={m.stale_after_ms} />
        <span class="num faint">{m.took_ms != null ? `${m.took_ms} ms` : '—'}</span>
        <span class:bad={m.ok === false}>{m.ok === false ? m.error : m.ok ? 'ok' : 'waiting'}</span>
      </div>
    {/each}
  </div>
</section>

<section class="panel block">
  <div class="panel-head"><h2>About</h2></div>
  <div class="panel-body muted">
    Pertal {live.version} — webapp v4. Live connection: {live.connected ? 'connected' : 'disconnected'}.
  </div>
</section>

<style>
  h1 { margin-bottom: var(--s4); }
  .block { margin-bottom: var(--s4); }
  .families { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: var(--s3); margin-bottom: var(--s4); }
  .family {
    display: flex; flex-direction: column; align-items: flex-start; gap: 6px; padding: var(--s3);
    background: var(--surface-2); border: 1px solid var(--border-2); border-radius: var(--r-lg); cursor: pointer; text-align: left;
  }
  .family[aria-pressed='true'] { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
  .swatch { display: flex; gap: 3px; }
  .swatch i { width: 22px; height: 22px; border-radius: 4px; border: 1px solid rgba(128, 128, 128, .25); }
  .mode { display: flex; align-items: center; gap: var(--s3); flex-wrap: wrap; }
  .mode .seg button { text-transform: capitalize; }
  .src { grid-template-columns: minmax(160px, 1.4fr) 60px 90px 70px minmax(0, 2fr); font-size: var(--fs-sm); }
  .src.header { font-size: var(--fs-xs); color: var(--ink-3); text-transform: uppercase; letter-spacing: .05em; }
  .bad { color: var(--warn); }
  @media (max-width: 720px) {
    .src { grid-template-columns: minmax(0, 1fr) auto; }
    .src > :nth-child(2), .src > :nth-child(4) { display: none; }
    .src > :nth-child(5) { grid-column: 1 / -1; font-size: var(--fs-xs); }
    .src.header { display: none; }
  }
</style>
