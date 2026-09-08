<script lang="ts">
  // Pi-hole — block rate, query counts, pause/resume, top-blocked domains.
  // Reads /api/pihole/summary (usePihole, 60s cadence). "Top blocked" is a
  // second, on-demand query (only enabled while shown) against
  // /api/pihole/top?count=10, 15s timeout, since it is heavier than the summary.
  //
  // Allow-only by construction: /api/pihole/allow can only whitelist a domain,
  // never add a block, so a mis-click here can never break resolution — it
  // replaces ssh-ing in to run `pihole allow`.
  //
  // A pause always carries a server-side timer, so blocking resumes on its own
  // even if this tab is closed — POST /api/pihole/blocking { enabled, seconds }.
  import type { WidgetProps } from '$lib/widgets/sdk';
  import { WidgetFrame, WidgetError, WidgetLoading, Pill } from '$lib/widgets/kit';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { get, post, ApiError } from '$lib/api/client';
  import { usePihole } from '$lib/api/queries';
  import { toast } from '$lib/stores/toast.svelte';

  // No configurable options for this widget (see registry.ts 'pihole' entry).
  let {}: WidgetProps = $props();

  const q = usePihole();
  const qc = useQueryClient();
  let showTop = $state(false);

  const top = createQuery(() => ({
    queryKey: ['pihole-top'],
    queryFn: () => get<{ domains: { domain: string; count: number }[] }>('/api/pihole/top?count=10', 15_000),
    enabled: showTop,
    retry: 0,
  }));

  const allow = createMutation(() => ({
    mutationFn: (domain: string) => post('/api/pihole/allow', { domain }, 15_000),
    onSuccess: (_d, domain) => {
      toast(`${domain} whitelisted`, 'ok');
      qc.invalidateQueries({ queryKey: ['pihole-top'] });
    },
    onError: (e: unknown) => toast(`Whitelist failed: ${e instanceof ApiError || e instanceof Error ? e.message : 'error'}`, 'crit'),
  }));

  const toggle = createMutation(() => ({
    mutationFn: (enable: boolean) => post('/api/pihole/blocking', { enabled: enable, seconds: 300 }, 15_000),
    onSuccess: (_d, enable) => {
      toast(enable ? 'Pi-hole blocking resumed' : 'Pi-hole paused for 5 minutes', 'ok');
      qc.invalidateQueries({ queryKey: ['pihole'] });
    },
    onError: (e: unknown) => toast(`Pi-hole: ${e instanceof ApiError || e instanceof Error ? e.message : 'error'}`, 'crit'),
  }));

  let enabled = $derived(q.data?.blocking?.enabled ?? true);
</script>

{#snippet statusPill()}
  <Pill tone={enabled ? 'ok' : 'warn'}>
    {enabled ? 'blocking' : `paused${q.data?.blocking?.timer ? ` ${q.data.blocking.timer}s` : ''}`}
  </Pill>
{/snippet}

{#if q.isError}
  <WidgetFrame title="Pi-hole"><WidgetError message={q.error instanceof Error ? q.error.message : 'Pi-hole unavailable'} /></WidgetFrame>
{:else if q.isLoading || !q.data}
  <WidgetFrame title="Pi-hole"><WidgetLoading /></WidgetFrame>
{:else}
  {@const d = q.data}
  <WidgetFrame title="Pi-hole" head={statusPill}>
    <div class="big-metric">
      {d.ads_percentage_today != null ? `${d.ads_percentage_today.toFixed(1)}%` : '—'}
      <small> blocked</small>
    </div>
    <div class="kv-rows">
      <div class="kv-row"><span>queries today</span><span>{d.dns_queries_today?.toLocaleString() ?? '—'}</span></div>
      <div class="kv-row"><span>blocked</span><span>{d.ads_blocked_today?.toLocaleString() ?? '—'}</span></div>
      <div class="kv-row"><span>clients</span><span>{d.unique_clients ?? '—'}</span></div>
      <div class="kv-row"><span>gravity</span><span>{d.gravity_domains?.toLocaleString() ?? '—'}</span></div>
    </div>
    {#if showTop}
      <div class="kv-rows top-domains">
        {#if top.isLoading}<span class="t-dim">loading…</span>{/if}
        {#if top.isError}<span class="t-dim">top domains unavailable</span>{/if}
        {#each top.data?.domains ?? [] as dm (dm.domain)}
          <div class="kv-row">
            <span class="mono top-domain" title={dm.domain}>{dm.domain}</span>
            <span>
              {dm.count.toLocaleString()}
              <button class="link-btn" disabled={allow.isPending} title={`Whitelist ${dm.domain}`} onclick={() => allow.mutate(dm.domain)}>allow</button>
            </span>
          </div>
        {/each}
      </div>
    {/if}
    <div class="w-actions">
      <button class="tb-btn" disabled={toggle.isPending} onclick={() => toggle.mutate(!enabled)}>
        {enabled ? 'Pause 5 min' : 'Resume blocking'}
      </button>
      <button class="tb-btn" onclick={() => (showTop = !showTop)}>
        {showTop ? 'Hide blocked' : 'Top blocked'}
      </button>
    </div>
  </WidgetFrame>
{/if}
