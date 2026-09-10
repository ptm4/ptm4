<script lang="ts">
  // Blocking status + pause/resume with a duration picker. A pause always carries
  // a server-side timer (POST /api/pihole/blocking {enabled,seconds}) — blocking
  // resumes on its own even if this tab closes.
  import { Pause, Play } from '@lucide/svelte';
  import { createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { post, ApiError } from '$lib/api/client';
  import type { PiholeSummary } from '$lib/api/types';
  import { toast } from '$lib/stores/toast.svelte';

  let { data }: { data: PiholeSummary | undefined } = $props();

  const PAUSES = [
    { label: '1 min', s: 60 },
    { label: '5 min', s: 300 },
    { label: '30 min', s: 1800 },
    { label: '1 hour', s: 3600 },
  ];

  const qc = useQueryClient();

  const blocking = createMutation(() => ({
    mutationFn: ({ enabled, seconds }: { enabled: boolean; seconds?: number }) =>
      post('/api/pihole/blocking', { enabled, seconds }, 15_000),
    onSuccess: (_d, v) => {
      toast(v.enabled ? 'Blocking resumed' : `Blocking paused for ${Math.round((v.seconds ?? 300) / 60)} min`, 'ok');
      qc.invalidateQueries({ queryKey: ['pihole'] });
    },
    onError: (e: unknown) => toast(`Pi-hole: ${e instanceof ApiError || e instanceof Error ? e.message : 'error'}`, 'crit', { sticky: true }),
  }));

  let enabled = $derived(data?.blocking?.enabled ?? true);
</script>

<section class="card">
  <div class="w-head">
    <span class="w-title">Blocking</span>
    <span class="w-meta">
      <span class="pill" data-s={enabled ? 'ok' : 'warn'}>
        {enabled ? 'active' : `paused${data?.blocking?.timer ? ` · ${Math.round(data.blocking.timer / 60)}m left` : ''}`}
      </span>
    </span>
  </div>
  <div class="big-metric">
    {data?.ads_percentage_today != null ? `${data.ads_percentage_today.toFixed(1)}%` : '—'}
    <small> of today's queries blocked</small>
  </div>
  <div class="kv-rows">
    <div class="kv-row"><span>queries today</span><span>{data?.dns_queries_today?.toLocaleString() ?? '—'}</span></div>
    <div class="kv-row"><span>blocked</span><span>{data?.ads_blocked_today?.toLocaleString() ?? '—'}</span></div>
    <div class="kv-row"><span>active clients</span><span>{data?.unique_clients ?? '—'}</span></div>
    <div class="kv-row"><span>gravity domains</span><span>{data?.gravity_domains?.toLocaleString() ?? '—'}</span></div>
  </div>
  <div class="w-actions">
    {#if enabled}
      {#each PAUSES as p (p.s)}
        <button class="tbtn" disabled={blocking.isPending} onclick={() => blocking.mutate({ enabled: false, seconds: p.s })}>
          <Pause size={14} aria-hidden="true" /> {p.label}
        </button>
      {/each}
    {:else}
      <button class="tbtn primary" disabled={blocking.isPending} onclick={() => blocking.mutate({ enabled: true })}>
        <Play size={14} aria-hidden="true" /> Resume now
      </button>
    {/if}
  </div>
  <p class="t-dim">A pause always carries a server-side timer — blocking resumes on its own even if this tab closes.</p>
</section>
