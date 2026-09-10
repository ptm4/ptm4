<script lang="ts">
  import { fmtBytesPerSec, fmtPct } from '$lib/format';
  import type { MonitorProcess } from '$lib/api/types';
  type ProcessRow = MonitorProcess & { monitorHost?: string };
  type Sort = 'cpu_pct' | 'memory_bytes' | 'pid' | 'program';
  let { rows, search, sort, descending, tree, paused, selected, onsearch, onsort, ontree, onpause, onselect }: { rows: ProcessRow[]; search: string; sort: Sort; descending: boolean; tree: boolean; paused: boolean; selected: MonitorProcess | null; onsearch: (value: string) => void; onsort: (value: Sort) => void; ontree: () => void; onpause: () => void; onselect: (value: ProcessRow) => void } = $props();
  const fmtBytes = (value: number | null | undefined) => {
    if (value == null) return '—'; const units = ['B', 'KiB', 'MiB', 'GiB']; let n = value; let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
    return `${n >= 10 || i === 0 ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`;
  };
</script>

<div class="processes">
  <div class="process-head"><strong>processes</strong><input id="monitor-search" placeholder="filter processes" value={search} oninput={(event) => onsearch((event.currentTarget as HTMLInputElement).value)} /><button class:on={tree} onclick={ontree}>tree</button><button class:on={paused} onclick={onpause}>{paused ? 'resume' : 'pause'}</button></div>
  <div class="process-scroll"><table><thead><tr><th>host</th><th><button onclick={() => onsort('pid')}>pid</button></th><th><button onclick={() => onsort('program')}>program</button></th><th>user</th><th>state</th><th>threads</th><th><button onclick={() => onsort('cpu_pct')}>cpu {sort === 'cpu_pct' ? (descending ? '↓' : '↑') : ''}</button></th><th><button onclick={() => onsort('memory_bytes')}>memory</button></th><th>read/s</th><th>write/s</th></tr></thead><tbody>{#each rows.slice(0, 500) as process (process.identity)}<tr class:on={selected?.identity === process.identity} onclick={() => onselect(process)}><td>{process.monitorHost ?? '—'}</td><td>{process.pid}</td><td title={process.command}>{tree && process.ppid ? '└─ ' : ''}{process.program}</td><td>{process.user}</td><td>{process.state}</td><td>{process.threads}</td><td>{fmtPct(process.cpu_pct)}</td><td>{fmtBytes(process.memory_bytes)}</td><td>{fmtBytesPerSec(process.read_bps)}</td><td>{fmtBytesPerSec(process.write_bps)}</td></tr>{/each}</tbody></table></div>
</div>

<style>
  .processes{min-height:0;height:100%;border:1px solid var(--border-2);background:var(--bg);display:flex;flex-direction:column;font-family:var(--mono);font-variant-numeric:tabular-nums}.process-head{display:flex;gap:5px;align-items:center;padding:6px;border-bottom:1px solid var(--border)}.process-head input{min-width:0;flex:1;background:var(--bg-inset);border:1px solid var(--border);color:var(--ink);font:inherit;padding:4px}.processes button{font:inherit;font-size:.86em;color:var(--ink-2);background:transparent;border:1px solid var(--border);padding:3px 7px;cursor:pointer}.processes button.on{color:var(--bg);background:var(--accent);border-color:var(--accent)}.process-scroll{overflow:auto;min-height:0;flex:1}table{width:100%;border-collapse:collapse;font-size:.86em;white-space:nowrap}th{text-align:left;position:sticky;top:0;background:var(--bg-inset);color:var(--ink-3)}th button{border:0!important;padding:4px!important}td,th{padding:4px 6px;border-bottom:1px solid var(--border)}tbody tr{cursor:pointer}tbody tr:hover,tbody tr.on{background:var(--accent-dim)}
</style>
