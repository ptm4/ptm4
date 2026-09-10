<script lang="ts">
  // weather: witty morning messages — list edits stay local (lifted into
  // BotPanel's `structured` state via onChange) and only persist on Save.
  import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
  import { Dices, X } from '@lucide/svelte';
  import { get, post, ApiError } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';
  import type { WittyReroll, WittyStatus } from '$lib/bots';

  let { enabled, names, onChange }: {
    enabled: boolean;
    names: string[];
    onChange: (names: string[]) => void;
  } = $props();

  function extraErrorMessage(e: unknown, fallback: string): string {
    return (e as ApiError)?.message ?? fallback;
  }

  const qc = useQueryClient();
  let draft = $state('');
  // The reroll response knows today's actual weather, so once it lands it is a
  // better "next up" than the weather-blind next_generic from GET /witty. The
  // remaining-count pairing expires it: any pool change (send, name rebuild)
  // shifts `remaining`, and the card falls back to fresh server data.
  let liveNext = $state<{ next: string; remaining?: number } | null>(null);

  const witty = createQuery(() => ({
    queryKey: ['bot-witty'],
    queryFn: () => get<WittyStatus>('/api/weather/witty', 10_000),
    retry: 0,
  }));

  const reroll = createMutation(() => ({
    mutationFn: () => post<WittyReroll>('/api/weather/witty/reroll', undefined, 35_000),
    onSuccess: (d) => {
      if (d?.ok) {
        liveNext = d.next ? { next: d.next, remaining: d.remaining } : null;
        toast(d.note ?? 'Rerolled — the skipped line stays in the cycle', 'ok');
        qc.invalidateQueries({ queryKey: ['bot-witty'] });
      } else {
        toast(`Reroll failed: ${d?.error ?? 'the bot reported an error'}`, 'crit');
      }
    },
    onError: (e: Error) => toast(extraErrorMessage(e, 'Reroll failed.'), 'crit'),
  }));

  function addName() {
    const n = draft.trim();
    if (!n) return;
    // Mirror the bot's PUT /config validation so a bad name fails here, at the
    // input, instead of failing the whole save with a bare server 400.
    if (!/^@?[A-Za-z0-9 .'_-]{1,40}$/.test(n)) {
      toast("Names can use letters, digits, spaces, . ' - _ and an optional leading @ (max 40 chars).", 'warn');
      return;
    }
    if (/^@?\s*(everyone|here)$/i.test(n)) {
      toast('That name would ping the whole channel every morning — pick another.', 'warn');
      return;
    }
    if (names.length >= 20) {
      toast('The bot caps the pool at 20 names.', 'warn');
      return;
    }
    draft = '';
    if (names.some((x) => x.toLowerCase() === n.toLowerCase())) return;
    onChange([...names, n]);
  }

  let pool = $derived(witty.data);
  // liveNext only holds while the pool hasn't moved under it (see above).
  let nextUp = $derived(
    (liveNext && liveNext.remaining === pool?.remaining ? liveNext.next : null) ?? pool?.next_generic ?? '—',
  );
</script>

<section class="card bot-extra{enabled ? '' : ' is-dim'}">
  <div class="w-head">
    <span class="w-title">Witty morning messages</span>
    {#if typeof pool?.pool_size === 'number'}<span class="w-meta">{pool.pool_size} templates</span>{/if}
  </div>
  {#if witty.isError}
    <p class="t-dim">Pool status unavailable — an old bot build may still be deploying.</p>
  {/if}
  {#if pool && pool.available === false}<p class="t-dim">{pool.reason ?? 'Witty pool unavailable.'}</p>{/if}
  {#if pool && pool.available !== false}
    <div class="kv-rows witty-pool">
      <div class="kv-row"><span>Lines left this cycle</span>
        <span>{pool.remaining ?? '—'}{typeof pool.cycle === 'number' ? ` (cycle ${pool.cycle})` : ''}</span></div>
      <div class="kv-row"><span>Next up*</span>
        <span>{nextUp}</span></div>
      <div class="kv-row"><span>Last posted</span>
        <span>{pool.last_posted?.text ?? '—'}</span></div>
    </div>
  {/if}
  <p class="form-note t-dim">
    *generic preview — the posted line adapts to the day's weather and weekday.
    "Preview" shows exactly what will post.
  </p>
  <div class="bot-list">
    {#each names as n, i (`${n}-${i}`)}
      <div class="bot-list-row">
        <span aria-hidden="true">🎯</span> <span>{n}</span>
        <span class="spacer"></span>
        <button class="tbtn sm danger" aria-label="Remove {n}"
          onclick={() => onChange(names.filter((_, j) => j !== i))}><X size={14} aria-hidden="true" /></button>
      </div>
    {/each}
    {#if names.length === 0}<p class="t-dim">No names — the one-liner needs at least one victim.</p>{/if}
  </div>
  <div class="bot-add-row">
    <input type="text" bind:value={draft} placeholder="first name / nickname / full name…"
      onkeydown={(e) => { if (e.key === 'Enter') addName(); }} />
    <button class="tbtn primary" onclick={addName}>Add</button>
  </div>
  <div class="w-actions">
    <button class="tbtn" disabled={reroll.isPending} onclick={() => reroll.mutate()}>
      <Dices size={14} aria-hidden="true" /> {reroll.isPending ? 'Rerolling…' : 'Reroll next line'}
    </button>
  </div>
  <p class="form-note t-dim">
    One line featuring a random name is appended after the message text each morning —
    generated locally, no API calls. Nothing repeats until the pool runs out, then it
    reshuffles itself. "Send now" uses up a line; "Reroll" skips today's pick without
    burning it. Name changes apply on "Save settings" and rebuild the pool.
  </p>
</section>
