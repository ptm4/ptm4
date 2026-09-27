<script lang="ts">
  // Container logs via the agent. Follow mode re-reads every 5s and keeps the view
  // pinned to the bottom unless you have scrolled up to read something.
  import { RefreshCw } from '@lucide/svelte';
  import { api } from '$lib/api';

  let { host, container }: { host: string; container: string } = $props();

  let lines = $state<{ ts: string | null; text: string }[]>([]);
  let error = $state<string | null>(null);
  let loading = $state(false);
  let tail = $state(300);
  let filter = $state('');
  let follow = $state(true);
  let box = $state<HTMLDivElement>();
  let pinned = true;

  async function load() {
    loading = true;
    try {
      const d = await api.logs(host, container, tail);
      lines = d.lines;
      error = null;
      if (pinned) queueMicrotask(() => box && (box.scrollTop = box.scrollHeight));
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  $effect(() => { void host; void container; void tail; lines = []; void load(); });
  $effect(() => {
    if (!follow) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  });

  const shown = $derived(filter.trim() ? lines.filter((l) => l.text.toLowerCase().includes(filter.trim().toLowerCase())) : lines);
  const level = (t: string) => (/\b(error|err|fatal|panic|exception|traceback|failed)\b/i.test(t) ? 'e' : /\b(warn|warning)\b/i.test(t) ? 'w' : '');
  const time = (ts: string | null) => (ts ? new Date(ts).toLocaleTimeString([], { hour12: false }) : '');
</script>

<div class="viewer">
  <div class="bar">
    <input class="field" type="search" placeholder="Filter lines…" bind:value={filter} />
    <select class="field" bind:value={tail} aria-label="Lines">
      {#each [100, 300, 1000, 2000] as n}<option value={n}>last {n}</option>{/each}
    </select>
    <label class="follow"><input type="checkbox" bind:checked={follow} /> Follow</label>
    <button class="btn icon" onclick={load} aria-label="Reload" disabled={loading}><RefreshCw size={14} class={loading ? 'spin' : ''} /></button>
    <span class="faint count">{shown.length}{filter ? ` of ${lines.length}` : ''} lines</span>
  </div>
  {#if error}
    <p class="err">{error}</p>
  {/if}
  <div class="log" bind:this={box} onscroll={() => { if (box) pinned = box.scrollHeight - box.scrollTop - box.clientHeight < 40; }}>
    {#each shown as l, i (i)}
      <div class="line {level(l.text)}"><span class="ts">{time(l.ts)}</span><span class="tx">{l.text}</span></div>
    {:else}
      {#if !error}<div class="faint pad">{loading ? 'Loading…' : 'No log lines.'}</div>{/if}
    {/each}
  </div>
</div>

<style>
  .viewer { display: flex; flex-direction: column; gap: 8px; }
  .bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .bar input[type='search'] { flex: 1; min-width: 160px; }
  .follow { display: flex; align-items: center; gap: 6px; font-size: var(--fs-sm); color: var(--ink-2); }
  .count { font-size: var(--fs-xs); }
  .log {
    height: min(62vh, 640px); overflow: auto; padding: 8px 0;
    background: var(--bg-inset); border: 1px solid var(--border); border-radius: var(--r);
    font: 12px/1.5 var(--mono);
  }
  .line { display: grid; grid-template-columns: 70px minmax(0, 1fr); gap: 10px; padding: 0 10px; }
  .line:hover { background: var(--surface-2); }
  .ts { color: var(--ink-3); user-select: none; }
  .tx { white-space: pre-wrap; word-break: break-word; color: var(--ink-2); }
  .line.w .tx { color: var(--warn); }
  .line.e .tx { color: var(--crit); }
  .err { margin: 0; padding: 8px 12px; border: 1px solid var(--warn); border-radius: var(--r); background: var(--warn-dim); color: var(--warn); font-size: var(--fs-sm); }
  .pad { padding: 10px; }
  @media (max-width: 720px) { .line { grid-template-columns: minmax(0, 1fr); gap: 0; } .ts { font-size: 10px; } }
</style>
