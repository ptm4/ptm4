<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { beforeNavigate, goto } from '$app/navigation';
  import Age from './Age.svelte';
  import { api, type ConsoleStatus } from '$lib/api';
  import { live } from '$lib/live.svelte';
  import { theme } from '$lib/theme.svelte';
  import { consoleHost, consolePath } from '$lib/console';

  let { host, path = 'system', hash = '' }: { host: string; path?: string; hash?: string } = $props();
  let status = $state<ConsoleStatus | null>(null);
  let error = $state<string | null>(null);
  let frame = $state<HTMLIFrameElement>();
  let source = $state('');
  let loaded = $state(false);
  const root = $derived(`/cp-${host}`);
  const snapshot = $derived(live.snapshots[`cockpit:${host}`]);
  const stamp = $derived(JSON.stringify(snapshot ?? null));
  const entry = $derived(status?.hosts.find((item) => item.id === host));
  const stale = $derived(!entry?.fetched_at || live.now - Date.parse(entry.fetched_at) > 5 * 60_000 || entry.stale);
  const ready = $derived(consoleHost(host) && status?.enabled === true && !error && entry?.ok === true && !stale && snapshot?.ok !== false);
  let leaving = false;
  beforeNavigate(({ to }) => { leaving = !to?.url.pathname.startsWith(`/console/${host}/`); });

  let generation = 0;
  async function load() {
    const current = ++generation;
    try {
      const result = await api.console();
      if (current === generation) { status = result; error = null; }
    } catch (e) {
      if (current === generation) error = (e as Error).message;
    }
  }
  $effect(() => { void stamp; void host; void load(); });
  $effect(() => {
    const mode = theme.mode === 'system' ? 'auto' : theme.mode;
    try { localStorage.setItem('shell:style', mode); } catch { /* private storage */ }
    // Cockpit reads its own storage; also notify its window when our mode changes.
    try {
      frame?.contentWindow?.dispatchEvent(new StorageEvent('storage', { key: 'shell:style', newValue: mode }));
    } catch { /* a frame may briefly be navigating */ }
  });
  $effect(() => {
    const safePath = consolePath(path);
    const safeHash = typeof hash === 'string' && /^\/[a-zA-Z0-9_.@:-]{1,200}$/.test(hash) ? `#${hash}` : '';
    if (!ready) { source = ''; loaded = false; return; }
    const next = `${root}/${safePath}${safeHash}`;
    try {
      if (frame?.contentWindow?.location.pathname === `${root}/${safePath}` && !safeHash) return;
    } catch { /* a frame can briefly be at about:blank */ }
    if (source !== next) { source = next; loaded = false; }
  });
  function mirror() {
    if (leaving || !page.url.pathname.startsWith(`/console/${host}/`) || !ready || !frame?.contentWindow || !loaded) return;
    try {
      const url = new URL(frame.contentWindow.location.href);
      if (url.origin !== location.origin || !url.pathname.startsWith(`${root}/`)) return;
      const candidate = url.pathname.slice(root.length + 1).replace(/\/$/, '') || 'system';
      if (consolePath(candidate) !== candidate) return;
      const next = `/console/${host}/${candidate}`;
      if (page.url.pathname !== next) void goto(next, { replaceState: true, noScroll: true, keepFocus: true, state: {} });
    } catch { /* accessing a frame during navigation may fail */ }
  }
  onMount(() => {
    const timer = setInterval(mirror, 1000);
    return () => { clearInterval(timer); generation++; };
  });
</script>

{#if consoleHost(host)}
  <div class="console-state faint">
    <span>
      {#if status && !status.enabled}Disabled here
      {:else if error || entry?.ok === false || (entry?.ok === true && stale)}Waiting for recovery
      {:else if ready}Connected
      {:else}Waiting for first response{/if}
      {#if entry?.fetched_at} · checked <Age at={entry.fetched_at} staleAfterMs={5 * 60_000} />{/if}
    </span>
    <a href="https://{host}.lan:9090/" target="_blank" rel="noreferrer">Sign in to Cockpit ↗</a>
  </div>
{/if}

{#if !consoleHost(host)}
  <div class="empty">Unknown Console host.</div>
{:else if status && !status.enabled}
  <div class="empty">Console is not available here. It is enabled on the deployed Pertal gateway.</div>
{:else if ready && source}
  <div class="frame-wrap">
    {#if !loaded}<div class="opening faint" role="status">Opening {host} Console…</div>{/if}
    <iframe bind:this={frame} src={source} title="Cockpit Console · {host}" onload={() => { loaded = true; mirror(); }}></iframe>
  </div>
{:else if error || entry?.ok === false || (entry?.ok === true && stale)}
  <div class="empty">
    <strong>{host} Console is unavailable.</strong>
    <p>{error ?? entry?.error ?? 'The last gateway response is stale.'}</p>
    <p>Last response <Age at={entry?.fetched_at} staleAfterMs={5 * 60_000} />. Pertal reconnects after the gateway recovers.</p>
  </div>
{:else}
  <div class="empty" role="status">Waiting for {host} Console…</div>
{/if}

<style>
  .console-state { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px; padding: 5px var(--s3); border-bottom: 1px solid var(--border); font-size: var(--fs-xs); }
  .frame-wrap { position: relative; flex: 1; min-height: 0; display: flex; }
  iframe { border: 0; width: 100%; height: 100%; flex: 1; background: var(--bg); }
  .opening { position: absolute; inset: 12px auto auto 12px; padding: 6px 10px; background: var(--surface); border-radius: var(--r); pointer-events: none; }
  .empty { margin: var(--s4); padding: var(--s4); }
</style>
