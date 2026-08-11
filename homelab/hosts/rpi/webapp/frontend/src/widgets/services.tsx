// Service widgets: app tiles and groups, Pi-hole, VPN, quick links, clock, weather.
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { get, post } from '../lib/api';
import { toast } from '../lib/toast';
import { useContainers, useLinkcheck, usePihole } from '../lib/queries';
import { ALL_LINKS, LINK_GROUPS, iconUrl, isExternal, type AppLink } from '../lib/links';
import { WidgetFrame, Pill, WidgetError, WidgetLoading } from './kit';

// ── app / app-group ─────────────────────────────────────────────────────────
function AppTile({ link, probe }: { link: AppLink; probe?: { up: boolean; error?: string } }) {
  const state = !link.checkOrigin ? 'none' : probe == null ? 'unknown' : probe.up ? 'ok' : 'crit';
  return (
    <a
      className="app-tile glass"
      href={link.url}
      target={isExternal(link.url) ? '_blank' : undefined}
      rel={isExternal(link.url) ? 'noreferrer' : undefined}
      title={probe && !probe.up ? `down: ${probe.error ?? 'no response'}` : link.label}
    >
      <img src={iconUrl(link.icon)} alt="" />
      <span className="app-label">{link.label}</span>
      {state !== 'none' && <span className="app-dot" data-s={state} />}
    </a>
  );
}

export function AppWidget({ options }: { options?: Record<string, unknown> }) {
  const label = options?.label as string | undefined;
  const check = useLinkcheck();
  const link = ALL_LINKS.find((l) => l.label === label);
  if (!link) return <WidgetFrame title="App"><WidgetError message={`unknown app '${label ?? ''}'`} /></WidgetFrame>;
  return (
    <div className="w-card w-bare">
      <AppTile link={link} probe={link.checkOrigin ? check.data?.origins[link.checkOrigin] : undefined} />
    </div>
  );
}

export function AppGroupWidget({ options }: { options?: Record<string, unknown> }) {
  const groupName = (options?.group as string) || 'Infrastructure';
  const check = useLinkcheck();
  const group = LINK_GROUPS.find((g) => g.group === groupName);
  if (!group) return <WidgetFrame title={groupName}><WidgetError message="unknown group" /></WidgetFrame>;
  return (
    <WidgetFrame title={groupName} scroll>
      <div className="links-grid tight">
        {group.links.map((l) => (
          <AppTile key={l.label} link={l} probe={l.checkOrigin ? check.data?.origins[l.checkOrigin] : undefined} />
        ))}
      </div>
    </WidgetFrame>
  );
}

// ── quick links (compact list) ──────────────────────────────────────────────
export function QuickLinksWidget() {
  const favs = ALL_LINKS.filter((l) => l.fav);
  return (
    <WidgetFrame title="Quick links" meta={<a href="/links">all {ALL_LINKS.length} →</a>} scroll>
      <div className="qlinks">
        {favs.map((l) => (
          <a key={l.label} className="qlink" href={l.url}
            target={isExternal(l.url) ? '_blank' : undefined}
            rel={isExternal(l.url) ? 'noreferrer' : undefined}>
            <img src={iconUrl(l.icon)} alt="" />
            {l.label}
          </a>
        ))}
      </div>
    </WidgetFrame>
  );
}

// ── pihole ──────────────────────────────────────────────────────────────────
export function PiholeWidget() {
  const q = usePihole();
  const qc = useQueryClient();
  const [showTop, setShowTop] = useState(false);

  const top = useQuery({
    queryKey: ['pihole-top'],
    queryFn: () => get<{ domains: { domain: string; count: number }[] }>('/api/pihole/top?count=10', 15_000),
    enabled: showTop,
  });

  // Allow-only by construction: this endpoint cannot add a block, so a mis-click
  // can never break resolution. Replaces ssh-ing in to run `pihole allow`.
  const allow = useMutation({
    mutationFn: (domain: string) => post('/api/pihole/allow', { domain }, 15_000),
    onSuccess: (_d, domain) => {
      toast(`${domain} whitelisted`, 'ok');
      qc.invalidateQueries({ queryKey: ['pihole-top'] });
    },
    onError: (e) => toast(`Whitelist failed: ${(e as Error).message}`, 'crit'),
  });

  // A pause ALWAYS carries a timer server-side, so blocking resumes on its own
  // even if this tab is closed.
  const toggle = useMutation({
    mutationFn: (enable: boolean) => post('/api/pihole/blocking', { enabled: enable, seconds: 300 }, 15_000),
    onSuccess: (_d, enable) => {
      toast(enable ? 'Pi-hole blocking resumed' : 'Pi-hole paused for 5 minutes', 'ok');
      qc.invalidateQueries({ queryKey: ['pihole'] });
    },
    onError: (e) => toast(`Pi-hole: ${(e as Error).message}`, 'crit'),
  });

  if (q.isError) return <WidgetFrame title="Pi-hole"><WidgetError message={(q.error as Error).message} /></WidgetFrame>;
  if (q.isLoading || !q.data) return <WidgetFrame title="Pi-hole"><WidgetLoading /></WidgetFrame>;

  const d = q.data;
  const enabled = d.blocking?.enabled ?? true;
  return (
    <WidgetFrame
      title="Pi-hole"
      meta={<Pill tone={enabled ? 'ok' : 'warn'}>{enabled ? 'blocking' : `paused${d.blocking?.timer ? ` ${d.blocking.timer}s` : ''}`}</Pill>}
    >
      <div className="big-metric">
        {d.ads_percentage_today != null ? `${d.ads_percentage_today.toFixed(1)}%` : '—'}
        <small> blocked</small>
      </div>
      <div className="kv-rows">
        <div className="kv-row"><span>queries today</span><span>{d.dns_queries_today?.toLocaleString() ?? '—'}</span></div>
        <div className="kv-row"><span>blocked</span><span>{d.ads_blocked_today?.toLocaleString() ?? '—'}</span></div>
        <div className="kv-row"><span>clients</span><span>{d.unique_clients ?? '—'}</span></div>
        <div className="kv-row"><span>gravity</span><span>{d.gravity_domains?.toLocaleString() ?? '—'}</span></div>
      </div>
      {showTop && (
        <div className="kv-rows top-domains">
          {top.isLoading && <span className="t-dim">loading…</span>}
          {top.isError && <span className="t-dim">top domains unavailable</span>}
          {(top.data?.domains ?? []).map((d) => (
            <div className="kv-row" key={d.domain}>
              <span className="mono top-domain" title={d.domain}>{d.domain}</span>
              <span>
                {d.count.toLocaleString()}
                {' '}
                <button className="link-btn" disabled={allow.isPending}
                  title={`Whitelist ${d.domain}`} onClick={() => allow.mutate(d.domain)}>allow</button>
              </span>
            </div>
          ))}
        </div>
      )}
      <div className="w-actions">
        <button className="tb-btn" disabled={toggle.isPending} onClick={() => toggle.mutate(!enabled)}>
          {enabled ? 'Pause 5 min' : 'Resume blocking'}
        </button>
        <button className="tb-btn" onClick={() => setShowTop((v) => !v)}>
          {showTop ? 'Hide blocked' : 'Top blocked'}
        </button>
      </div>
    </WidgetFrame>
  );
}

// ── vpn ─────────────────────────────────────────────────────────────────────
// Gluetun's health is the health of the five containers sharing its netns — if
// gluetun is down they are all down by design, not five separate faults.
export function VpnWidget() {
  const q = useContainers();
  const nn = q.data?.hosts.find((h) => h.host === 'noblenumbat');
  const gluetun = nn?.containers.find((c) => c.name === 'gluetun');
  const behind = ['qbittorrent', 'sabnzbd', 'prowlarr', 'flaresolverr', 'slskd'];
  const behindRows = (nn?.containers ?? []).filter((c) => behind.includes(c.name));

  return (
    <WidgetFrame
      title="VPN"
      meta={<Pill tone={gluetun ? (gluetun.up ? 'ok' : 'crit') : undefined}>
        {gluetun ? (gluetun.up ? 'up' : 'down') : 'unknown'}
      </Pill>}
    >
      {!gluetun && <div className="t-dim">gluetun not in the latest report</div>}
      <div className="kv-rows">
        {behindRows.map((c) => (
          <div className="kv-row" key={c.name}>
            <span className="mono">{c.name}</span>
            <span className={c.up ? '' : 't-crit'}>{c.up ? 'up' : 'down'}</span>
          </div>
        ))}
      </div>
    </WidgetFrame>
  );
}

// ── clock ───────────────────────────────────────────────────────────────────
export function ClockWidget({ options }: { options?: Record<string, unknown> }) {
  const showSeconds = options?.seconds !== false;
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), showSeconds ? 1000 : 20_000);
    return () => clearInterval(id);
  }, [showSeconds]);

  return (
    <div className="w-card glass clock">
      <div className="clock-time">
        {now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', ...(showSeconds ? { second: '2-digit' } : {}) })}
      </div>
      <div className="clock-date">
        {now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })}
      </div>
    </div>
  );
}

// ── weather ─────────────────────────────────────────────────────────────────
// Reuses the weather bot's Open-Meteo preview — no new upstream, no API key.
// The payload is a Discord webhook body: { payload: { embeds: [ { fields } ] } }.
interface WeatherPreview {
  payload?: {
    embeds?: { title?: string; description?: string; fields?: { name: string; value: string }[] }[];
  };
}

// Each field is one location: name "☁️ BELLEROSE, NY", value a **bold** temp line.
function parseLocation(f: { name: string; value: string }) {
  const m = f.name.match(/^(\S+)\s+(.*)$/);
  const icon = m?.[1] ?? '';
  const place = (m?.[2] ?? f.name).replace(/,\s*[A-Z]{2}$/, '');
  const plain = f.value.replace(/\*\*/g, '');
  const temps = plain.match(/-?\d+°/g) ?? [];
  return { icon, place, high: temps[0] ?? '', low: temps[1] ?? '', detail: plain.split('\n')[0] };
}

export function WeatherWidget({ options }: { options?: Record<string, unknown> }) {
  const limit = (options?.limit as number) ?? 4;
  const q = useQuery({
    queryKey: ['weather-preview'],
    queryFn: () => get<WeatherPreview>('/api/weather/preview', 40_000),
    refetchInterval: 30 * 60_000,
    retry: 0,
  });

  if (q.isError) return <WidgetFrame title="Weather"><WidgetError message="weather bot unreachable" /></WidgetFrame>;
  if (q.isLoading) return <WidgetFrame title="Weather"><WidgetLoading /></WidgetFrame>;

  const embed = q.data?.payload?.embeds?.[0];
  // The bot pads its Discord grid with blank spacer fields — drop those.
  const locations = (embed?.fields ?? [])
    .filter((f) => (f.name || '').replace(/[​\s]/g, '') !== '')
    .slice(0, limit)
    .map(parseLocation);

  return (
    <WidgetFrame title="Weather" meta={<span className="t-dim">today</span>} scroll>
      {locations.length === 0 && <div className="t-dim">No forecast in the latest payload.</div>}
      <div className="wx-grid">
        {locations.map((l) => (
          <div className="wx" key={l.place}>
            <span className="wx-icon" aria-hidden>{l.icon}</span>
            <span className="wx-place">{l.place}</span>
            <span className="wx-temp">{l.high}{l.low && <small> / {l.low}</small>}</span>
          </div>
        ))}
      </div>
    </WidgetFrame>
  );
}
