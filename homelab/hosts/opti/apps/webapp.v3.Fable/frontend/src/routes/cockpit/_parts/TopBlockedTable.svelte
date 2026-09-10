<script lang="ts">
  // Top-blocked domains today, count selectable (10/15/25), with one-click
  // whitelisting. /api/pihole/allow is allow-only by construction — a mis-click
  // here can never add a block, so it safely replaces ssh-ing in for `pihole allow`.
  import { ShieldCheck } from '@lucide/svelte';
  import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { get, post, ApiError } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';

  let count = $state(15);

  const top = createQuery(() => ({
    queryKey: ['pihole-top', count],
    queryFn: () => get<{ domains: { domain: string; count: number }[] }>(`/api/pihole/top?count=${count}`, 15_000),
    refetchInterval: 60_000,
    retry: 0,
  }));

  const qc = useQueryClient();

  const allow = createMutation(() => ({
    mutationFn: (domain: string) => post('/api/pihole/allow', { domain }, 15_000),
    onSuccess: (_d, domain) => {
      toast(`${domain} whitelisted`, 'ok');
      qc.invalidateQueries({ queryKey: ['pihole-top'] });
    },
    onError: (e: unknown) => toast(`Whitelist failed: ${e instanceof ApiError || e instanceof Error ? e.message : 'error'}`, 'crit'),
  }));
</script>

<section class="card">
  <div class="w-head">
    <span class="w-title">Top blocked today</span>
    <span class="w-meta">
      <select class="input" bind:value={count}>
        {#each [10, 15, 25] as n (n)}
          <option value={n}>{n}</option>
        {/each}
      </select>
    </span>
  </div>
  {#if top.isError}<p class="t-dim">Unavailable — {top.error instanceof Error ? top.error.message : 'error'}</p>{/if}
  {#if top.isLoading}<div class="spin"></div>{/if}
  <table class="detail-table">
    <tbody>
      {#each top.data?.domains ?? [] as row (row.domain)}
        <tr>
          <td class="mono ct-image" title={row.domain}>{row.domain}</td>
          <td>{row.count.toLocaleString()}</td>
          <td>
            <button class="tbtn sm" disabled={allow.isPending}
              title={`Whitelist ${row.domain} (allow-only — this can never add a block)`}
              onclick={() => allow.mutate(row.domain)}>
              <ShieldCheck size={14} aria-hidden="true" /> Allow
            </button>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
  <p class="t-dim">Replaces ssh-ing in for <span class="mono">pihole allow</span> — Teams telemetry topping the list is normal.</p>
</section>
