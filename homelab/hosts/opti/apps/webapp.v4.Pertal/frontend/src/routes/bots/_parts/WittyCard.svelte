<script lang="ts">
  // Weather bot: witty morning messages. Name edits stay local (lifted into BotPanel via
  // onChange) and only persist on "Save settings". Re-roll is a job (routes/bots.js).
  import { Dices, X } from '@lucide/svelte';
  import { botCall, BOT_BY_ID, botError, type WittyReroll, type WittyStatus } from '$lib/bots';

  let { enabled, names, onChange }: { enabled: boolean; names: string[]; onChange: (names: string[]) => void } = $props();

  let pool = $state<WittyStatus | null>(null);
  let poolError = $state(false);
  let draft = $state('');
  let msg = $state<{ ok: boolean; text: string } | null>(null);
  let rerolling = $state(false);
  // The re-roll answer knows today's weather, so it beats the weather-blind next_generic
  // until the pool moves (a send or a name rebuild changes `remaining`).
  let liveNext = $state<{ next: string; remaining?: number } | null>(null);

  async function load() {
    try { pool = await botCall<WittyStatus>('/api/weather/witty'); poolError = false; } catch { poolError = true; }
  }
  $effect(() => { void load(); });

  async function reroll() {
    rerolling = true; msg = null;
    try {
      const d = await botCall<WittyReroll>('/api/weather/witty/reroll', { method: 'POST', timeoutMs: 35_000 });
      if (d?.ok) {
        liveNext = d.next ? { next: d.next, remaining: d.remaining } : null;
        msg = { ok: true, text: d.note ?? 'Re-rolled. The skipped line stays in the cycle.' };
        await load();
      } else msg = { ok: false, text: `Re-roll failed: ${d?.error ?? 'the bot reported an error'}` };
    } catch (e) { msg = { ok: false, text: botError(BOT_BY_ID.weather, e) }; } finally { rerolling = false; }
  }

  function add() {
    const n = draft.trim();
    if (!n) return;
    // Mirrors the bot's PUT /config validation so a bad name fails here, not on save.
    if (!/^@?[A-Za-z0-9 .'_-]{1,40}$/.test(n)) { msg = { ok: false, text: "Names can use letters, digits, spaces, . ' - _ and an optional leading @ (40 characters at most)." }; return; }
    if (/^@?\s*(everyone|here)$/i.test(n)) { msg = { ok: false, text: 'That name would ping the whole channel every morning. Pick another.' }; return; }
    if (names.length >= 20) { msg = { ok: false, text: 'The bot caps the pool at 20 names.' }; return; }
    draft = '';
    if (!names.some((x) => x.toLowerCase() === n.toLowerCase())) onChange([...names, n]);
  }
  const nextUp = $derived((liveNext && liveNext.remaining === pool?.remaining ? liveNext.next : null) ?? pool?.next_generic ?? '—');
</script>

<section class="panel" class:dim={!enabled}>
  <div class="panel-head"><h2>Witty morning messages</h2>{#if typeof pool?.pool_size === 'number'}<span class="faint">{pool.pool_size} templates</span>{/if}</div>
  <div class="panel-body body">
    {#if poolError}<p class="faint">Pool status unavailable.</p>{/if}
    {#if pool && pool.available === false}<p class="faint">{pool.reason ?? 'Witty pool unavailable.'}</p>{/if}
    {#if pool && pool.available !== false}
      <div class="kv">
        <span class="faint">Lines left this cycle</span><span>{pool.remaining ?? '—'}{typeof pool.cycle === 'number' ? ` (cycle ${pool.cycle})` : ''}</span>
        <span class="faint">Next up*</span><span>{nextUp}</span>
        <span class="faint">Last posted</span><span>{pool.last_posted?.text ?? '—'}</span>
      </div>
    {/if}
    <small class="faint">*Generic preview. The posted line adapts to the day's weather and weekday; "Preview" shows exactly what will post.</small>
    <div class="rows list">
      {#each names as n, i (`${n}-${i}`)}
        <div class="row item"><span>{n}</span><button class="btn icon ghost" aria-label="Remove {n}" onclick={() => onChange(names.filter((_, j) => j !== i))}><X size={14} /></button></div>
      {:else}
        <p class="faint">No names. The one-liner needs at least one.</p>
      {/each}
    </div>
    <div class="add">
      <input class="field" type="text" bind:value={draft} placeholder="first name, nickname or full name" onkeydown={(e) => { if (e.key === 'Enter') add(); }} />
      <button class="btn primary" onclick={add}>Add</button>
    </div>
    {#if msg}<p class:crit={!msg.ok} class="small">{msg.text}</p>{/if}
    <div><button class="btn" disabled={rerolling} onclick={reroll}><Dices size={14} /> {rerolling ? 'Re-rolling…' : 'Re-roll next line'}</button></div>
    <small class="faint">"Post now" uses up a line; "Re-roll" skips today's pick without burning it. Name changes apply on "Save settings" and rebuild the pool.</small>
  </div>
</section>

<style>
  .dim { opacity: .75; }
  .body { display: flex; flex-direction: column; gap: var(--s3); }
  .kv { display: grid; grid-template-columns: max-content 1fr; gap: 6px var(--s4); font-size: var(--fs-sm); }
  .list { border: 1px solid var(--border); border-radius: var(--r); }
  .item { grid-template-columns: 1fr auto; padding: 4px var(--s3); font-size: var(--fs-sm); }
  .list p { margin: 0; padding: 6px var(--s3); }
  .add { display: flex; gap: 8px; }
  .add input { flex: 1; min-width: 0; }
  .small { font-size: var(--fs-sm); margin: 0; }
  .crit { color: var(--crit); }
</style>
