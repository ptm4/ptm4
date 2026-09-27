<script lang="ts">
  // Ctrl/Cmd+K: jump to any resource or page. Arrow keys + Enter, Escape to close.
  import { goto } from '$app/navigation';
  import StatusDot from './StatusDot.svelte';
  import { live } from '$lib/live.svelte';
  import { NAV } from '$lib/nav';

  let { open = $bindable(false) }: { open?: boolean } = $props();
  let q = $state('');
  let idx = $state(0);
  let input = $state<HTMLInputElement>();

  type Hit = { href: string; label: string; sub: string; status?: string };
  const hits = $derived.by((): Hit[] => {
    const needle = q.trim().toLowerCase();
    const pages: Hit[] = NAV.filter((n) => n.ready).map((n) => ({ href: n.href, label: n.label, sub: 'page' }));
    const res: Hit[] = live.resources.map((r) => ({
      href: `/r/${r.id}`, label: r.name, sub: r.type === 'host' ? 'host' : `${r.kind} on ${r.host}`, status: r.status,
    }));
    const all = [...pages, ...res];
    if (!needle) return all.slice(0, 12);
    return all.filter((h) => `${h.label} ${h.sub}`.toLowerCase().includes(needle)).slice(0, 12);
  });

  $effect(() => {
    if (open) { q = ''; idx = 0; queueMicrotask(() => input?.focus()); }
  });
  $effect(() => { void q; idx = 0; });

  function go(h: Hit | undefined) {
    if (!h) return;
    open = false;
    goto(h.href);
  }
  function onkey(e: KeyboardEvent) {
    if (e.key === 'ArrowDown') { idx = Math.min(idx + 1, hits.length - 1); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { idx = Math.max(idx - 1, 0); e.preventDefault(); }
    else if (e.key === 'Enter') { go(hits[idx]); e.preventDefault(); }
    else if (e.key === 'Escape') { open = false; }
  }
</script>

{#if open}
  <div class="scrim" role="presentation" onclick={() => (open = false)}></div>
  <div class="palette" role="dialog" aria-label="Search">
    <input bind:this={input} bind:value={q} onkeydown={onkey} placeholder="Search resources and pages…" aria-label="Search" />
    <ul role="listbox">
      {#each hits as h, i (h.href)}
        <li role="option" aria-selected={i === idx}>
          <button class:sel={i === idx} onclick={() => go(h)} onmouseenter={() => (idx = i)}>
            {#if h.status}<StatusDot status={h.status} />{:else}<span class="spacer"></span>{/if}
            <span class="label">{h.label}</span>
            <span class="faint">{h.sub}</span>
          </button>
        </li>
      {:else}
        <li class="empty">No match</li>
      {/each}
    </ul>
  </div>
{/if}

<style>
  .scrim { position: fixed; inset: 0; z-index: 60; background: rgba(0, 0, 0, .45); }
  .palette {
    position: fixed; z-index: 61; left: 50%; top: 12vh; transform: translateX(-50%);
    width: min(560px, calc(100vw - 24px));
    background: var(--surface); border: 1px solid var(--border-2); border-radius: var(--r-lg);
    box-shadow: var(--shadow); overflow: hidden;
  }
  input {
    width: 100%; height: 46px; padding: 0 16px; border: 0; border-bottom: 1px solid var(--border);
    background: transparent; font-size: var(--fs-md); outline: none;
  }
  ul { list-style: none; margin: 0; padding: 4px; max-height: 50vh; overflow: auto; }
  button {
    width: 100%; display: flex; align-items: center; gap: 10px; padding: 8px 10px;
    border: 0; border-radius: var(--r); background: transparent; cursor: pointer; text-align: left;
  }
  button.sel { background: var(--accent-dim); }
  .label { flex: 1; }
  .spacer { width: 8px; }
</style>
