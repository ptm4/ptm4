// The Discord bot fleet — five bots, one panel. Every bot speaks the same control
// API (status/config/send/preview), so the panel is driven by the field table in
// lib/bots.ts. Structured config gets a real editor where one exists (the extras
// cards: locations, witty names, teams); anything else structured is carried
// through a save verbatim via each bot's `passthrough`.
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as Tabs from '@radix-ui/react-tabs';
import { Eye, Send } from 'lucide-react';
import { get, put, post, ApiError } from '../lib/api';
import { toast } from '../lib/toast';
import { localeDateTime } from '../lib/format';
import { Modal } from '../components/Modal';
import {
  JellyfinCheckCard, LocationsCard, TeamsCard, VrsCard, WittyCard,
} from '../components/BotExtras';
import {
  BOTS, type BotConfig, type BotDef, type BotPreview, type BotStatus,
  type SportsTeam, type WeatherLocation,
} from '../lib/bots';

// Which config key each structured editor owns. Owned keys are seeded from the
// fetched config into `structured` state, edited client-side by the extras
// cards, and written back on save — overriding any stale passthrough copy.
const EXTRA_KEYS: Partial<Record<NonNullable<BotDef['extras']>[number], string>> = {
  geocode: 'locations',
  witty: 'witty_names',
  teams: 'teams',
};

function ownedKeys(bot: BotDef): string[] {
  return (bot.extras ?? []).map((e) => EXTRA_KEYS[e]).filter((k): k is string => Boolean(k));
}

export default function BotsPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') ?? BOTS[0].id;

  return (
    <Tabs.Root value={tab} onValueChange={(v) => setParams({ tab: v }, { replace: true })}>
      <Tabs.List className="bot-tabs glass">
        {BOTS.map((b) => (
          <Tabs.Trigger key={b.id} value={b.id} className="bot-tab">
            <span aria-hidden>{b.icon}</span> {b.label}
          </Tabs.Trigger>
        ))}
      </Tabs.List>
      {BOTS.map((b) => (
        <Tabs.Content key={b.id} value={b.id}>
          <BotPanel bot={b} />
        </Tabs.Content>
      ))}
    </Tabs.Root>
  );
}

function botErrorMessage(bot: BotDef, e: unknown): string {
  const err = e as ApiError;
  if (err?.status === 502) return `${bot.container} unreachable — check \`docker ps\` on rpi.`;
  if (err?.status === 400) return `Rejected: ${err.message}`;
  return err?.message ?? 'Request failed.';
}

function BotPanel({ bot }: { bot: BotDef }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<BotConfig>({});
  const [structured, setStructured] = useState<BotConfig>({});
  // Pending list edits survive config refetches (toggle, window focus) until saved.
  const [structuredDirty, setStructuredDirty] = useState(false);
  const [preview, setPreview] = useState<BotPreview | null>(null);

  const editStructured = (patch: BotConfig) => {
    setStructured((s) => ({ ...s, ...patch }));
    setStructuredDirty(true);
  };

  const status = useQuery({
    queryKey: ['bot-status', bot.id],
    queryFn: () => get<BotStatus>(`/api/${bot.id}/status`, 10_000),
    refetchInterval: 60_000,
    retry: 0,
  });
  const config = useQuery({
    queryKey: ['bot-config', bot.id],
    queryFn: () => get<BotConfig>(`/api/${bot.id}/config`, 10_000),
    retry: 0,
  });

  // Server config seeds the form and the structured editors. Refetches reseed
  // both, EXCEPT the structured lists while they hold unsaved edits — a toggle
  // or window-focus refetch must not wipe a half-finished list edit.
  useEffect(() => {
    if (!config.data) return;
    setForm(config.data);
    if (!structuredDirty) {
      const s: BotConfig = {};
      for (const k of ownedKeys(bot)) if (config.data[k] !== undefined) s[k] = config.data[k];
      setStructured(s);
    }
  }, [config.dataUpdatedAt]);

  const save = useMutation({
    mutationFn: (body: BotConfig) => put(`/api/${bot.id}/config`, body, 20_000),
    onSuccess: () => {
      toast(`${bot.label} settings saved — rescheduled`, 'ok');
      setStructuredDirty(false);
      qc.invalidateQueries({ queryKey: ['bot-config', bot.id] });
      qc.invalidateQueries({ queryKey: ['bot-status', bot.id] });
      qc.invalidateQueries({ queryKey: ['bot-witty'] }); // name changes rebuild the pool
    },
    onError: (e) => toast(botErrorMessage(bot, e), 'crit', { ttlMs: 8000 }),
  });

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => put(`/api/${bot.id}/config`, { enabled }, 15_000),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bot-status', bot.id] });
      qc.invalidateQueries({ queryKey: ['bot-config', bot.id] });
    },
    onError: (e) => toast(botErrorMessage(bot, e), 'crit'),
  });

  const send = useMutation({
    mutationFn: () => post<{ ok?: boolean; detail?: string }>(`/api/${bot.id}/send`, undefined, 130_000),
    onSuccess: (d) => {
      if (d?.ok) toast(`${bot.label} posted to Discord`, 'ok');
      else toast(`Send failed: ${d?.detail ?? 'the bot reported an error'}`, 'crit', { sticky: true });
      qc.invalidateQueries({ queryKey: ['bot-status', bot.id] });
      qc.invalidateQueries({ queryKey: ['bot-witty'] }); // a real send consumes a line
    },
    onError: (e) => toast(botErrorMessage(bot, e), 'crit', { sticky: true }),
  });

  const buildPreview = useMutation({
    mutationFn: () => get<BotPreview>(`/api/${bot.id}/preview`, 130_000),
    onSuccess: (d) => setPreview(d),
    onError: (e) => toast(botErrorMessage(bot, e), 'crit'),
  });

  const enabled = (status.data?.enabled ?? form.enabled) === true;

  const submit = () => {
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
  };

  if (status.isError && config.isError) {
    return <div className="glass card t-crit">{botErrorMessage(bot, status.error)}</div>;
  }

  return (
    <div className="bot-panel">
      <section className="glass card bot-status" data-s={enabled ? 'ok' : undefined}>
        <header>
          <span className="status-badge" data-s={enabled ? 'ok' : 'unknown'}>{enabled ? 'ACTIVE' : 'PAUSED'}</span>
          <h3>Daily post</h3>
          <span className="spacer" />
          <button className={`tb-btn toggle ${enabled ? 'on' : 'off'}`}
            disabled={toggle.isPending} onClick={() => toggle.mutate(!enabled)}>
            {enabled ? 'Enabled' : 'Disabled'}
          </button>
        </header>
        <div className="kv-rows">
          <div className="kv-row"><span>Next post</span><span>{localeDateTime(status.data?.next_post_at)}</span></div>
          <div className="kv-row"><span>Last post</span><span>{localeDateTime(status.data?.last_post_at)}</span></div>
          <div className="kv-row"><span>Last result</span><span>{status.data?.last_status ?? '—'}</span></div>
        </div>
        <div className="w-actions">
          <button className="tb-btn" disabled={send.isPending} onClick={() => send.mutate()}>
            <Send /> {send.isPending ? 'Sending…' : 'Send now'}
          </button>
          <button className="tb-btn" disabled={buildPreview.isPending} onClick={() => buildPreview.mutate()}>
            <Eye /> {buildPreview.isPending ? 'Building…' : 'Preview'}
          </button>
        </div>
      </section>

      <section className="glass card">
        <div className="w-head"><span className="w-title">Settings</span></div>
        {config.isLoading && <div className="spin" />}
        <div className="form-rows">
          {bot.fields.map((f) => (
            <label key={f.key} className="form-row">
              <span>{f.label}</span>
              {f.type === 'boolean' ? (
                <input type="checkbox" checked={form[f.key] === true}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.checked })} />
              ) : f.type === 'select' ? (
                <select value={String(form[f.key] ?? '')}
                  onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}>
                  {f.choices?.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              ) : (
                <input
                  type={f.type === 'time' ? 'time' : f.type === 'number' ? 'number' : f.type === 'password' ? 'password' : 'text'}
                  value={String(form[f.key] ?? '')}
                  placeholder={f.placeholder}
                  onChange={(e) => setForm({
                    ...form,
                    [f.key]: f.type === 'number' ? Number(e.target.value) : e.target.value,
                  })}
                />
              )}
              {f.help && <span className="form-help t-dim">{f.help}</span>}
            </label>
          ))}
        </div>
        {bot.passthrough.length > 0 && config.data && (
          <p className="t-dim form-note">
            Preserved on save: {bot.passthrough.filter((k) => config.data![k] !== undefined).join(', ') || 'none'}
          </p>
        )}
        <div className="w-actions">
          {/* No saving until config has loaded — a save seeded from an empty
              form would wholesale-replace lists the server still has. */}
          <button className="tb-btn primary" disabled={save.isPending || !config.data} onClick={submit}>
            {save.isPending ? 'Saving…' : 'Save settings'}
          </button>
        </div>
      </section>

      {bot.extras?.includes('witty') && (
        <WittyCard
          enabled={form.witty_enabled === true}
          names={(structured.witty_names as string[] | undefined) ?? []}
          onChange={(names) => editStructured({ witty_names: names })}
        />
      )}
      {bot.extras?.includes('geocode') && (
        <LocationsCard
          locations={(structured.locations as WeatherLocation[] | undefined) ?? []}
          onChange={(locations) => editStructured({ locations })}
        />
      )}
      {bot.extras?.includes('teams') && (
        <TeamsCard
          teams={(structured.teams as SportsTeam[] | undefined) ?? []}
          onChange={(teams) => editStructured({ teams })}
        />
      )}
      {bot.extras?.includes('jellyfin-check') && <JellyfinCheckCard />}
      {bot.extras?.includes('vrs') && <VrsCard />}

      {preview && (
        <Modal open onClose={() => setPreview(null)} title="Preview — as it will appear in Discord" wide>
          <EmbedPreview preview={preview} />
        </Modal>
      )}
    </div>
  );
}

// Discord-style embed rendering. **bold** is the only markdown Discord embeds use
// in these payloads; everything else is plain text (and JSX-escaped).
function mdBold(s: string) {
  return s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**')
      ? <strong key={i}>{part.slice(2, -2)}</strong>
      : <span key={i}>{part}</span>);
}

function EmbedPreview({ preview }: { preview: BotPreview }) {
  const embed = preview.payload?.embeds?.[0] ?? {};
  const fields = (embed.fields ?? []).filter((f) => (f.name || '').replace(/[​\s]/g, '') !== '');
  return (
    <>
      {preview.payload?.content && <div className="msg-content">{mdBold(preview.payload.content)}</div>}
      <div className="embed-preview">
        {preview.payload?.username && <div className="embed-author">{preview.payload.username}</div>}
        {embed.title && <div className="embed-title">{embed.title}</div>}
        {embed.description && <div className="embed-desc">{mdBold(embed.description)}</div>}
        <div className="embed-fields">
          {fields.map((f, i) => (
            <div key={i} className={`embed-field${f.inline ? ' inline' : ''}`}>
              <div className="embed-field-name">{f.name}</div>
              <div className="embed-field-value">{mdBold(f.value)}</div>
            </div>
          ))}
        </div>
        {embed.footer && <div className="embed-footer">{embed.footer.text}</div>}
      </div>
      {preview.failed && preview.failed.length > 0 && (
        <div className="t-crit">No data for: {preview.failed.join(', ')}</div>
      )}
    </>
  );
}
