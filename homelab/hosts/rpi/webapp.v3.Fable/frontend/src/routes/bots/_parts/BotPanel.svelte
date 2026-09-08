<script lang="ts">
  // Per-bot panel: status card (enable toggle, send-now, preview), the generic
  // settings form, and whichever structured editors this bot owns. Bot proxies
  // legitimately 502 when the container is down — no retries, a friendly message
  // pointing at `docker ps <container>` instead of a bare fetch failure.
  import { untrack } from 'svelte';
  import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
  import { Eye, Send } from '@lucide/svelte';
  import { get, put, post, ApiError } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';
  import { localeDateTime } from '$lib/format';
  import Modal from '$lib/components/Modal.svelte';
  import BotForm from './BotForm.svelte';
  import EmbedPreview from './EmbedPreview.svelte';
  import WittyCard from './WittyCard.svelte';
  import LocationsCard from './LocationsCard.svelte';
  import TeamsCard from './TeamsCard.svelte';
  import VrsCard from './VrsCard.svelte';
  import JellyfinCheckCard from './JellyfinCheckCard.svelte';
  import type {
    BotConfig, BotDef, BotPreview as BotPreviewT, BotStatus, SportsTeam, WeatherLocation,
  } from '$lib/bots';

  let { bot }: { bot: BotDef } = $props();

  // Which config key each structured editor owns. Owned keys are seeded from the
  // fetched config into `structured` state, edited client-side by the extras
  // cards, and written back on save — overriding any stale passthrough copy.
  const EXTRA_KEYS: Record<string, string> = { geocode: 'locations', witty: 'witty_names', teams: 'teams' };
  function ownedKeys(b: BotDef): string[] {
    return (b.extras ?? []).map((e) => EXTRA_KEYS[e]).filter((k): k is string => Boolean(k));
  }

  function botErrorMessage(e: unknown): string {
    const err = e as ApiError;
    if (err?.status === 502) return `${bot.container} unreachable — check \`docker ps\` on rpi.`;
    if (err?.status === 400) return `Rejected: ${err.message}`;
    return err?.message ?? 'Request failed.';
  }

  const qc = useQueryClient();
  let form = $state<BotConfig>({});
  let structured = $state<BotConfig>({});
  // Pending list edits survive config refetches (toggle, window focus) until saved.
  let structuredDirty = $state(false);
  let preview = $state<BotPreviewT | null>(null);

  function editStructured(patch: BotConfig) {
    structured = { ...structured, ...patch };
    structuredDirty = true;
  }

  const status = createQuery(() => ({
    queryKey: ['bot-status', bot.id],
    queryFn: () => get<BotStatus>(`/api/${bot.id}/status`, 10_000),
    refetchInterval: 60_000,
    retry: 0,
  }));
  const config = createQuery(() => ({
    queryKey: ['bot-config', bot.id],
    queryFn: () => get<BotConfig>(`/api/${bot.id}/config`, 10_000),
    retry: 0,
  }));

  // Server config seeds the form and the structured editors. Refetches reseed
  // both, EXCEPT the structured lists while they hold unsaved edits — a toggle
  // or window-focus refetch must not wipe a half-finished list edit.
  $effect(() => {
    const data = config.data;
    // dataUpdatedAt is read only to force a rerun on every completed fetch, even
    // one that resolves to a reference-equal object.
    config.dataUpdatedAt;
    if (!data) return;
    form = data;
    if (!untrack(() => structuredDirty)) {
      const s: BotConfig = {};
      for (const k of ownedKeys(bot)) if (data[k] !== undefined) s[k] = data[k];
      structured = s;
    }
  });

  const save = createMutation(() => ({
    mutationFn: (body: BotConfig) => put(`/api/${bot.id}/config`, body, 20_000),
    onSuccess: () => {
      toast(`${bot.label} settings saved — rescheduled`, 'ok');
      structuredDirty = false;
      qc.invalidateQueries({ queryKey: ['bot-config', bot.id] });
      qc.invalidateQueries({ queryKey: ['bot-status', bot.id] });
      qc.invalidateQueries({ queryKey: ['bot-witty'] }); // name changes rebuild the pool
    },
    onError: (e: Error) => toast(botErrorMessage(e), 'crit', { ttlMs: 8000 }),
  }));

  const toggle = createMutation(() => ({
    mutationFn: (enabled: boolean) => put(`/api/${bot.id}/config`, { enabled }, 15_000),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bot-status', bot.id] });
      qc.invalidateQueries({ queryKey: ['bot-config', bot.id] });
    },
    onError: (e: Error) => toast(botErrorMessage(e), 'crit'),
  }));

  const send = createMutation(() => ({
    mutationFn: () => post<{ ok?: boolean; detail?: string }>(`/api/${bot.id}/send`, undefined, 130_000),
    onSuccess: (d) => {
      if (d?.ok) toast(`${bot.label} posted to Discord`, 'ok');
      else toast(`Send failed: ${d?.detail ?? 'the bot reported an error'}`, 'crit', { sticky: true });
      qc.invalidateQueries({ queryKey: ['bot-status', bot.id] });
      qc.invalidateQueries({ queryKey: ['bot-witty'] }); // a real send consumes a line
    },
    onError: (e: Error) => toast(botErrorMessage(e), 'crit', { sticky: true }),
  }));

  const buildPreview = createMutation(() => ({
    mutationFn: () => get<BotPreviewT>(`/api/${bot.id}/preview`, 130_000),
    onSuccess: (d) => { preview = d; },
    onError: (e: Error) => toast(botErrorMessage(e), 'crit'),
  }));

  let enabled = $derived((status.data?.enabled ?? form.enabled) === true);

  function submit() {
    // The bot 400s an empty locations list and the save is atomic — fail it
    // here, pointing at the right card, instead of with a bare server message.
    if (Array.isArray(structured.locations) && structured.locations.length === 0) {
      toast('The weather bot needs at least one location — add one before saving.', 'warn');
      return;
    }
    const body: BotConfig = { enabled };
    for (const f of bot.fields) body[f.key] = form[f.key];
    // Structured config this form doesn't model must survive the round trip.
    for (const key of bot.passthrough) if (config.data?.[key] !== undefined) body[key] = config.data[key];
    // The extras cards' working copies commit here — Save is the single commit point.
    Object.assign(body, structured);
    save.mutate(body);
  }
</script>

{#if status.isError && config.isError}
  <div class="card t-crit">{botErrorMessage(status.error)}</div>
{:else}
  <div class="bot-panel">
    <section class="card bot-status" data-s={enabled ? 'ok' : undefined}>
      <header>
        <span class="status-badge" data-s={enabled ? 'ok' : 'unknown'}>{enabled ? 'ACTIVE' : 'PAUSED'}</span>
        <h3>Daily post</h3>
        <span class="spacer"></span>
        <button class="tbtn toggle {enabled ? 'on' : 'off'}"
          disabled={toggle.isPending} onclick={() => toggle.mutate(!enabled)}>
          {enabled ? 'Enabled' : 'Disabled'}
        </button>
      </header>
      <div class="kv-rows">
        <div class="kv-row"><span>Next post</span><span>{localeDateTime(status.data?.next_post_at)}</span></div>
        <div class="kv-row"><span>Last post</span><span>{localeDateTime(status.data?.last_post_at)}</span></div>
        <div class="kv-row"><span>Last result</span><span>{status.data?.last_status ?? '—'}</span></div>
      </div>
      <div class="w-actions">
        <button class="tbtn" disabled={send.isPending} onclick={() => send.mutate()}>
          <Send size={14} aria-hidden="true" /> {send.isPending ? 'Sending…' : 'Send now'}
        </button>
        <button class="tbtn" disabled={buildPreview.isPending} onclick={() => buildPreview.mutate()}>
          <Eye size={14} aria-hidden="true" /> {buildPreview.isPending ? 'Building…' : 'Preview'}
        </button>
      </div>
    </section>

    <section class="card">
      <div class="w-head"><span class="w-title">Settings</span></div>
      {#if config.isLoading}<div class="spin"></div>{/if}
      <BotForm fields={bot.fields} bind:form />
      {#if bot.passthrough.length > 0 && config.data}
        <p class="t-dim form-note">
          Preserved on save: {bot.passthrough.filter((k) => config.data?.[k] !== undefined).join(', ') || 'none'}
        </p>
      {/if}
      <div class="w-actions">
        <!-- No saving until config has loaded — a save seeded from an empty
             form would wholesale-replace lists the server still has. -->
        <button class="tbtn primary" disabled={save.isPending || !config.data} onclick={submit}>
          {save.isPending ? 'Saving…' : 'Save settings'}
        </button>
      </div>
    </section>

    {#if bot.extras?.includes('witty')}
      <WittyCard
        enabled={form.witty_enabled === true}
        names={(structured.witty_names as string[] | undefined) ?? []}
        onChange={(names) => editStructured({ witty_names: names })}
      />
    {/if}
    {#if bot.extras?.includes('geocode')}
      <LocationsCard
        locations={(structured.locations as WeatherLocation[] | undefined) ?? []}
        onChange={(locations) => editStructured({ locations })}
      />
    {/if}
    {#if bot.extras?.includes('teams')}
      <TeamsCard
        teams={(structured.teams as SportsTeam[] | undefined) ?? []}
        onChange={(teams) => editStructured({ teams })}
      />
    {/if}
    {#if bot.extras?.includes('jellyfin-check')}<JellyfinCheckCard />{/if}
    {#if bot.extras?.includes('vrs')}<VrsCard />{/if}
  </div>
{/if}

{#if preview}
  <Modal open title="Preview — as it will appear in Discord" wide onclose={() => (preview = null)}>
    <EmbedPreview preview={preview} />
  </Modal>
{/if}
