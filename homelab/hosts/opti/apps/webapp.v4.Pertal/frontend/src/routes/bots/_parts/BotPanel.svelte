<script lang="ts">
  // One bot: status (enable toggle, post now, preview), the generic settings form, and
  // whichever structured editors this bot owns. Ported from v3.Fable's BotPanel.
  import { untrack } from 'svelte';
  import { Eye, Send, Plug, ListOrdered } from '@lucide/svelte';
  import { actions } from '$lib/actions.svelte';
  import { botCall, botError, type BotConfig, type BotDef, type BotPreview, type BotStatus, type JellyfinCheck, type SportsTeam, type VrsList, type WeatherLocation } from '$lib/bots';
  import WittyCard from './WittyCard.svelte';
  import LocationsCard from './LocationsCard.svelte';
  import TeamsCard from './TeamsCard.svelte';
  import EmbedPreview from './EmbedPreview.svelte';

  let { bot }: { bot: BotDef } = $props();

  // Which config key each structured editor owns. Owned keys are seeded from the fetched
  // config, edited by the extras cards, and written back on save.
  const EXTRA_KEYS: Record<string, string> = { geocode: 'locations', witty: 'witty_names', teams: 'teams' };
  const owned = $derived((bot.extras ?? []).map((e) => EXTRA_KEYS[e]).filter(Boolean));

  let status = $state<BotStatus | null>(null);
  let config = $state<BotConfig | null>(null);
  let loadError = $state<string | null>(null);
  let form = $state<BotConfig>({});
  let structured = $state<BotConfig>({});
  let structuredDirty = $state(false);  // pending list edits survive refetches until saved
  let busy = $state<string | null>(null);
  let notice = $state<{ ok: boolean; text: string } | null>(null);
  let preview = $state<BotPreview | null>(null);
  let vrs = $state<VrsList | null>(null);
  let jfCheck = $state<{ ok: boolean; text: string } | null>(null);
  let wittyKey = $state(0); // bumped to make the witty card reload after a save or send

  async function loadStatus() {
    try { status = await botCall<BotStatus>(`/api/${bot.id}/status`); } catch (e) { status = null; loadError = botError(bot, e); }
  }
  async function loadConfig() {
    try {
      const data = await botCall<BotConfig>(`/api/${bot.id}/config`);
      config = data; form = { ...data }; loadError = null;
      if (!untrack(() => structuredDirty)) {
        const s: BotConfig = {};
        for (const k of owned) if (data[k] !== undefined) s[k] = data[k];
        structured = s;
      }
    } catch (e) { loadError = botError(bot, e); }
  }
  $effect(() => {
    void loadStatus(); void loadConfig();
    const t = setInterval(loadStatus, 60_000);
    return () => clearInterval(t);
  });

  function editStructured(patch: BotConfig) { structured = { ...structured, ...patch }; structuredDirty = true; }
  const enabled = $derived((status?.enabled ?? form.enabled) === true);

  async function run(label: string, fn: () => Promise<void>) {
    busy = label; notice = null;
    try { await fn(); } catch (e) { notice = { ok: false, text: botError(bot, e) }; actions.fail(`${label}: ${bot.label} bot`, e); } finally { busy = null; }
  }

  const put = (body: BotConfig, timeoutMs = 20_000) => botCall(`/api/${bot.id}/config`, { method: 'PUT', body: JSON.stringify(body), timeoutMs });

  function save() {
    // The bot 400s an empty locations list and the save is atomic: say so up front.
    if (Array.isArray(structured.locations) && structured.locations.length === 0) {
      notice = { ok: false, text: 'The weather bot needs at least one location. Add one before saving.' };
      return;
    }
    const body: BotConfig = { enabled };
    for (const f of bot.fields) body[f.key] = form[f.key];
    for (const key of bot.passthrough) if (config?.[key] !== undefined) body[key] = config[key];
    Object.assign(body, structured);
    void run('Save settings', async () => {
      await put(body);
      structuredDirty = false;
      notice = { ok: true, text: `${bot.label} settings saved and rescheduled.` };
      wittyKey++;
      await Promise.all([loadConfig(), loadStatus()]);
    });
  }
  const toggle = () => run(enabled ? 'Pause' : 'Enable', async () => {
    await put({ enabled: !enabled }, 15_000);
    await Promise.all([loadConfig(), loadStatus()]);
  });
  const send = () => run('Post now', async () => {
    const d = await botCall<{ ok?: boolean; detail?: string }>(`/api/${bot.id}/send`, { method: 'POST', timeoutMs: 130_000 });
    notice = d?.ok ? { ok: true, text: `${bot.label} posted to Discord.` } : { ok: false, text: `Send failed: ${d?.detail ?? 'the bot reported an error'}` };
    wittyKey++;
    await loadStatus();
  });
  const buildPreview = () => run('Preview', async () => {
    preview = await botCall<BotPreview>(`/api/${bot.id}/preview`, { timeoutMs: 130_000 });
  });
  const loadVrs = () => run('VRS list', async () => { vrs = await botCall<VrsList>('/api/hltv/vrs', { timeoutMs: 25_000 }); });
  const testJellyfin = () => run('Test connection', async () => {
    const d = await botCall<JellyfinCheck>('/api/jellyfin/check', { timeoutMs: 20_000 });
    jfCheck = d?.ok
      ? { ok: true, text: `Connected to ${d.server_name ?? 'Jellyfin'}${d.version ? ` (v${d.version})` : ''}` }
      : { ok: false, text: d?.error ?? 'Check failed: the bot reported an error.' };
  });
  const when = (s?: string | null) => (s ? new Date(s).toLocaleString() : '—');
</script>

{#if loadError && !config && !status}
  <p class="banner">{loadError}</p>
{:else}
  {#if notice}<p class="banner" class:ok={notice.ok}>{notice.text}</p>{/if}
  <div class="grid">
    <section class="panel">
      <div class="panel-head">
        <span class="badge {enabled ? 'accent' : ''}">{enabled ? 'Active' : 'Paused'}</span>
        <h2>Daily post</h2>
        <button class="btn" disabled={busy !== null} onclick={toggle}>{enabled ? 'Pause' : 'Enable'}</button>
      </div>
      <div class="panel-body kv">
        <span class="faint">Next post</span><span>{when(status?.next_post_at)}</span>
        <span class="faint">Last post</span><span>{when(status?.last_post_at)}</span>
        <span class="faint">Last result</span><span>{status?.last_status ?? '—'}</span>
      </div>
      <div class="panel-body acts">
        <button class="btn" disabled={busy !== null} onclick={send}><Send size={14} /> {busy === 'Post now' ? 'Sending…' : 'Post now'}</button>
        <button class="btn" disabled={busy !== null} onclick={buildPreview}><Eye size={14} /> {busy === 'Preview' ? 'Building…' : 'Preview'}</button>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head"><h2>Settings</h2></div>
      <div class="panel-body form">
        {#each bot.fields as f (f.key)}
          <label class="frow">
            <span>{f.label}</span>
            {#if f.type === 'boolean'}
              <input type="checkbox" checked={form[f.key] === true} onchange={(e) => (form = { ...form, [f.key]: e.currentTarget.checked })} />
            {:else if f.type === 'select'}
              <select class="field" value={String(form[f.key] ?? '')} onchange={(e) => (form = { ...form, [f.key]: e.currentTarget.value })}>
                {#each f.choices ?? [] as c (c.value)}<option value={c.value}>{c.label}</option>{/each}
              </select>
            {:else}
              <input class="field" type={f.type === 'time' ? 'time' : f.type === 'number' ? 'number' : f.type === 'password' ? 'password' : 'text'}
                value={String(form[f.key] ?? '')} placeholder={f.placeholder}
                oninput={(e) => (form = { ...form, [f.key]: f.type === 'number' ? Number(e.currentTarget.value) : e.currentTarget.value })} />
            {/if}
            {#if f.help}<small class="faint">{f.help}</small>{/if}
          </label>
        {/each}
        {#if bot.passthrough.length && config}
          <small class="faint">Kept as is on save: {bot.passthrough.filter((k) => config?.[k] !== undefined).join(', ') || 'none'}</small>
        {/if}
      </div>
      <div class="panel-body acts">
        <!-- No saving until config has loaded: a save from an empty form would replace lists the bot still has. -->
        <button class="btn primary" disabled={busy !== null || !config} onclick={save}>{busy === 'Save settings' ? 'Saving…' : 'Save settings'}</button>
      </div>
    </section>

    {#if bot.extras?.includes('witty')}
      {#key wittyKey}
        <WittyCard enabled={form.witty_enabled === true} names={(structured.witty_names as string[] | undefined) ?? []}
          onChange={(names) => editStructured({ witty_names: names })} />
      {/key}
    {/if}
    {#if bot.extras?.includes('geocode')}
      <LocationsCard locations={(structured.locations as WeatherLocation[] | undefined) ?? []} onChange={(locations) => editStructured({ locations })} />
    {/if}
    {#if bot.extras?.includes('teams')}
      <TeamsCard teams={(structured.teams as SportsTeam[] | undefined) ?? []} onChange={(teams) => editStructured({ teams })} />
    {/if}
    {#if bot.extras?.includes('jellyfin-check')}
      <section class="panel">
        <div class="panel-head"><h2>Server connection</h2></div>
        <div class="panel-body">
          {#if jfCheck}<p class:crit={!jfCheck.ok}>{jfCheck.text}</p>{/if}
          <button class="btn" disabled={busy !== null} onclick={testJellyfin}><Plug size={14} /> {busy === 'Test connection' ? 'Checking…' : 'Test connection'}</button>
          <p class="faint small">Probes the saved Jellyfin URL and API key. Save settings first if you just changed either.</p>
        </div>
      </section>
    {/if}
    {#if bot.extras?.includes('vrs')}
      <section class="panel">
        <div class="panel-head"><h2>Valve Regional Standings</h2>{#if vrs?.as_of}<span class="faint">as of {vrs.as_of}</span>{/if}</div>
        <div class="panel-body">
          {#if vrs?.teams}
            <ol class="vrs">{#each vrs.teams as t, i (i)}<li>{t}</li>{/each}</ol>
          {/if}
          <button class="btn" disabled={busy !== null} onclick={loadVrs}><ListOrdered size={14} /> {busy === 'VRS list' ? 'Fetching…' : vrs ? 'Refresh VRS list' : 'Show VRS list'}</button>
          <p class="faint small">The official Valve ranking, refreshed about weekly. It is the only ranking the digest uses.</p>
        </div>
      </section>
    {/if}
  </div>

  {#if preview}
    <section class="panel preview">
      <div class="panel-head"><h2>Preview, as it will appear in Discord</h2><button class="btn ghost" onclick={() => (preview = null)}>Close</button></div>
      <div class="panel-body"><EmbedPreview {preview} /></div>
    </section>
  {/if}
{/if}

<style>
  .banner { padding: 8px 12px; border: 1px solid var(--warn); border-radius: var(--r); background: var(--warn-dim); color: var(--warn); font-size: var(--fs-sm); margin: 0 0 var(--s3); }
  .banner.ok { border-color: var(--accent); background: var(--accent-dim); color: var(--accent); }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 380px), 1fr)); gap: var(--s3); align-items: start; }
  .kv { display: grid; grid-template-columns: max-content 1fr; gap: 6px var(--s4); font-size: var(--fs-sm); }
  .acts { display: flex; gap: 8px; flex-wrap: wrap; border-top: 1px solid var(--border); }
  .form { display: flex; flex-direction: column; gap: var(--s3); }
  .frow { display: grid; grid-template-columns: 160px minmax(0, 1fr); gap: 4px var(--s3); align-items: center; font-size: var(--fs-sm); }
  .frow small { grid-column: 2; }
  .frow input[type='checkbox'] { justify-self: start; }
  .small { font-size: var(--fs-xs); }
  .crit { color: var(--crit); }
  .vrs { margin: 0 0 var(--s3); padding-left: 1.6em; font-size: var(--fs-sm); columns: 2; }
  .preview { margin-top: var(--s3); }
  @media (max-width: 720px) { .frow { grid-template-columns: 1fr; } .frow small { grid-column: 1; } }
</style>
