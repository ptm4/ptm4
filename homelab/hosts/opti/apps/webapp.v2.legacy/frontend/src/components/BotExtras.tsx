// Structured-config editors for the bot panel — the cards the generic field
// renderer in pages/Bots.tsx can't express: the weather bot's witty pool and
// locations, the sports bot's team list, hltv's VRS viewer, jellyfin's
// connection check. List edits stay client-side (lifted into BotPanel's
// `structured` state) and only persist when the panel's "Save settings" runs —
// the same one-commit-point contract the legacy app had.
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Dices, ListOrdered, MapPin, Plug, Search, X } from 'lucide-react';
import { get, post, type ApiError } from '../lib/api';
import { toast } from '../lib/toast';
import type {
  GeocodeResult, JellyfinCheck, SportsTeam, VrsList, WeatherLocation,
  WittyReroll, WittyStatus,
} from '../lib/bots';

function extraErrorMessage(e: unknown, fallback: string): string {
  return (e as ApiError)?.message ?? fallback;
}

// ── weather: witty morning messages ──────────────────────────────────────────

export function WittyCard({ enabled, names, onChange }: {
  enabled: boolean;
  names: string[];
  onChange: (names: string[]) => void;
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState('');
  // The reroll response knows today's actual weather, so once it lands it is a
  // better "next up" than the weather-blind next_generic from GET /witty. The
  // remaining-count pairing expires it: any pool change (send, name rebuild)
  // shifts `remaining`, and the card falls back to fresh server data.
  const [liveNext, setLiveNext] = useState<{ next: string; remaining?: number } | null>(null);

  const witty = useQuery({
    queryKey: ['bot-witty'],
    queryFn: () => get<WittyStatus>('/api/weather/witty', 10_000),
    retry: 0,
  });

  const reroll = useMutation({
    mutationFn: () => post<WittyReroll>('/api/weather/witty/reroll', undefined, 35_000),
    onSuccess: (d) => {
      if (d?.ok) {
        setLiveNext(d.next ? { next: d.next, remaining: d.remaining } : null);
        toast(d.note ?? 'Rerolled — the skipped line stays in the cycle', 'ok');
        qc.invalidateQueries({ queryKey: ['bot-witty'] });
      } else {
        toast(`Reroll failed: ${d?.error ?? 'the bot reported an error'}`, 'crit');
      }
    },
    onError: (e) => toast(extraErrorMessage(e, 'Reroll failed.'), 'crit'),
  });

  const addName = () => {
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
    setDraft('');
    if (names.some((x) => x.toLowerCase() === n.toLowerCase())) return;
    onChange([...names, n]);
  };

  const pool = witty.data;
  // liveNext only holds while the pool hasn't moved under it (see above).
  const nextUp = (liveNext && liveNext.remaining === pool?.remaining ? liveNext.next : null)
    ?? pool?.next_generic ?? '—';
  return (
    <section className={`glass card bot-extra${enabled ? '' : ' is-dim'}`}>
      <div className="w-head">
        <span className="w-title">Witty morning messages</span>
        {typeof pool?.pool_size === 'number' && <span className="w-meta">{pool.pool_size} templates</span>}
      </div>
      {witty.isError && (
        <p className="t-dim">Pool status unavailable — an old bot build may still be deploying.</p>
      )}
      {pool && pool.available === false && <p className="t-dim">{pool.reason ?? 'Witty pool unavailable.'}</p>}
      {pool && pool.available !== false && (
        <div className="kv-rows witty-pool">
          <div className="kv-row"><span>Lines left this cycle</span>
            <span>{pool.remaining ?? '—'}{typeof pool.cycle === 'number' ? ` (cycle ${pool.cycle})` : ''}</span></div>
          <div className="kv-row"><span>Next up*</span>
            <span>{nextUp}</span></div>
          <div className="kv-row"><span>Last posted</span>
            <span>{pool.last_posted?.text ?? '—'}</span></div>
        </div>
      )}
      <p className="form-note t-dim">
        *generic preview — the posted line adapts to the day's weather and weekday.
        “Preview” shows exactly what will post.
      </p>
      <div className="bot-list">
        {names.map((n, i) => (
          <div key={`${n}-${i}`} className="bot-list-row">
            <span aria-hidden>🎯</span> <span>{n}</span>
            <span className="spacer" />
            <button className="tb-btn sm danger" aria-label={`Remove ${n}`}
              onClick={() => onChange(names.filter((_, j) => j !== i))}><X /></button>
          </div>
        ))}
        {names.length === 0 && <p className="t-dim">No names — the one-liner needs at least one victim.</p>}
      </div>
      <div className="bot-add-row">
        <input type="text" value={draft} placeholder="first name / nickname / full name…"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') addName(); }} />
        <button className="tb-btn primary" onClick={addName}>Add</button>
      </div>
      <div className="w-actions">
        <button className="tb-btn" disabled={reroll.isPending} onClick={() => reroll.mutate()}>
          <Dices /> {reroll.isPending ? 'Rerolling…' : 'Reroll next line'}
        </button>
      </div>
      <p className="form-note t-dim">
        One line featuring a random name is appended after the message text each morning —
        generated locally, no API calls. Nothing repeats until the pool runs out, then it
        reshuffles itself. “Send now” uses up a line; “Reroll” skips today’s pick without
        burning it. Name changes apply on “Save settings” and rebuild the pool.
      </p>
    </section>
  );
}

// ── weather: locations ───────────────────────────────────────────────────────

// Display-name abbreviation for US results, matching the legacy app's habit of
// "Bellerose, NY" rather than "Bellerose, New York".
const US_STATES: Record<string, string> = {
  Alabama: 'AL', Alaska: 'AK', Arizona: 'AZ', Arkansas: 'AR', California: 'CA',
  Colorado: 'CO', Connecticut: 'CT', Delaware: 'DE', Florida: 'FL', Georgia: 'GA',
  Hawaii: 'HI', Idaho: 'ID', Illinois: 'IL', Indiana: 'IN', Iowa: 'IA',
  Kansas: 'KS', Kentucky: 'KY', Louisiana: 'LA', Maine: 'ME', Maryland: 'MD',
  Massachusetts: 'MA', Michigan: 'MI', Minnesota: 'MN', Mississippi: 'MS',
  Missouri: 'MO', Montana: 'MT', Nebraska: 'NE', Nevada: 'NV',
  'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM', 'New York': 'NY',
  'North Carolina': 'NC', 'North Dakota': 'ND', Ohio: 'OH', Oklahoma: 'OK',
  Oregon: 'OR', Pennsylvania: 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC',
  'South Dakota': 'SD', Tennessee: 'TN', Texas: 'TX', Utah: 'UT', Vermont: 'VT',
  Virginia: 'VA', Washington: 'WA', 'West Virginia': 'WV', Wisconsin: 'WI',
  Wyoming: 'WY', 'District of Columbia': 'DC',
};

export function LocationsCard({ locations, onChange }: {
  locations: WeatherLocation[];
  onChange: (locations: WeatherLocation[]) => void;
}) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState<GeocodeResult[] | null>(null);

  const search = useMutation({
    mutationFn: (query: string) =>
      get<{ results?: GeocodeResult[] }>(`/api/weather/geocode?q=${encodeURIComponent(query)}`, 20_000),
    onSuccess: (d) => setResults(d?.results ?? []),
    onError: (e) => toast(extraErrorMessage(e, 'Location search failed.'), 'crit'),
  });

  const add = (r: GeocodeResult) => {
    setQ('');
    setResults(null);
    if (locations.some((l) => l.lat === r.lat && l.lon === r.lon)) return; // already listed
    const region = r.country === 'US' ? (US_STATES[r.admin1 ?? ''] ?? r.admin1) : r.admin1;
    onChange([...locations, { name: region ? `${r.name}, ${region}` : r.name, lat: r.lat, lon: r.lon }]);
  };

  return (
    <section className="glass card bot-extra">
      <div className="w-head">
        <span className="w-title">Locations ({locations.length})</span>
      </div>
      <div className="bot-list">
        {locations.map((l, i) => (
          <div key={`${l.name}-${i}`} className="bot-list-row">
            <MapPin aria-hidden /> <span>{l.name}</span>
            <span className="spacer" />
            <span className="bot-list-meta mono">{Number(l.lat).toFixed(4)}, {Number(l.lon).toFixed(4)}</span>
            <button className="tb-btn sm danger" aria-label={`Remove ${l.name}`}
              onClick={() => onChange(locations.filter((_, j) => j !== i))}><X /></button>
          </div>
        ))}
        {locations.length === 0 && <p className="t-dim">No locations — add one below.</p>}
      </div>
      <div className="bot-add-row">
        <input type="text" value={q} placeholder="city / town name…"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && q.trim()) search.mutate(q.trim()); }} />
        <button className="tb-btn" disabled={search.isPending || !q.trim()}
          onClick={() => search.mutate(q.trim())}>
          <Search /> {search.isPending ? 'Searching…' : 'Search'}
        </button>
      </div>
      {results && (
        <div className="geo-results">
          {results.map((r, i) => (
            <button key={i} className="tb-btn" onClick={() => add(r)}>
              {r.name}{r.admin1 ? `, ${r.admin1}` : ''}
              {' '}<span className="t-dim">({r.country ?? '?'} · {r.lat}, {r.lon})</span>
            </button>
          ))}
          {results.length === 0 && <p className="t-dim">No matches.</p>}
        </div>
      )}
      <p className="form-note t-dim">Changes here are applied when you hit “Save settings”.</p>
    </section>
  );
}

// ── sports: teams ────────────────────────────────────────────────────────────

// NBA only by design — the bot's league support hasn't grown past it.
const SPORTS_LEAGUES = [{ value: 'nba', label: 'NBA' }];
const LEAGUE_EMOJI: Record<string, string> = { nba: '🏀' };

export function TeamsCard({ teams, onChange }: {
  teams: SportsTeam[];
  onChange: (teams: SportsTeam[]) => void;
}) {
  const [league, setLeague] = useState(SPORTS_LEAGUES[0].value);
  const [q, setQ] = useState('');
  const [results, setResults] = useState<SportsTeam[] | null>(null);

  const search = useMutation({
    mutationFn: (query: string) =>
      get<{ results?: SportsTeam[] }>(
        `/api/sports/teams?league=${encodeURIComponent(league)}&q=${encodeURIComponent(query)}`, 25_000),
    onSuccess: (d) => setResults(d?.results ?? []),
    onError: (e) => toast(extraErrorMessage(e, 'Team search failed.'), 'crit'),
  });

  const add = (t: SportsTeam) => {
    if (!teams.some((x) => x.league === t.league && x.abbrev === t.abbrev)) onChange([...teams, t]);
    setQ('');
    setResults(null);
  };

  return (
    <section className="glass card bot-extra">
      <div className="w-head">
        <span className="w-title">Teams ({teams.length})</span>
      </div>
      <div className="bot-list">
        {teams.map((t, i) => (
          <div key={`${t.abbrev ?? t.name}-${i}`} className="bot-list-row">
            <span aria-hidden>{LEAGUE_EMOJI[t.league ?? ''] ?? '🏟️'}</span> <span>{t.name}</span>
            <span className="spacer" />
            <span className="bot-list-meta mono">
              {(t.league ?? '').toUpperCase()}{t.abbrev ? ` · ${t.abbrev}` : ''}
            </span>
            <button className="tb-btn sm danger" aria-label={`Remove ${t.name}`}
              onClick={() => onChange(teams.filter((_, j) => j !== i))}><X /></button>
          </div>
        ))}
        {teams.length === 0 && <p className="t-dim">No teams — search below to add one.</p>}
      </div>
      <div className="bot-add-row">
        <select value={league} onChange={(e) => setLeague(e.target.value)}>
          {SPORTS_LEAGUES.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
        </select>
        <input type="text" value={q} placeholder="team name…"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && q.trim()) search.mutate(q.trim()); }} />
        <button className="tb-btn" disabled={search.isPending || !q.trim()}
          onClick={() => search.mutate(q.trim())}>
          <Search /> {search.isPending ? 'Searching…' : 'Search'}
        </button>
      </div>
      {results && (
        <div className="geo-results">
          {results.map((t, i) => (
            <button key={i} className="tb-btn" onClick={() => add(t)}>
              {t.name} <span className="t-dim">({(t.league ?? '').toUpperCase()}{t.abbrev ? ` · ${t.abbrev}` : ''})</span>
            </button>
          ))}
          {results.length === 0 && <p className="t-dim">No matches.</p>}
        </div>
      )}
      <p className="form-note t-dim">Changes here are applied when you hit “Save settings”.</p>
    </section>
  );
}

// ── hltv: VRS viewer ─────────────────────────────────────────────────────────

export function VrsCard() {
  const [vrs, setVrs] = useState<VrsList | null>(null);
  const load = useMutation({
    mutationFn: () => get<VrsList>('/api/hltv/vrs', 25_000),
    onSuccess: (d) => setVrs(d),
    onError: (e) => toast(extraErrorMessage(e, 'VRS fetch failed.'), 'crit'),
  });

  return (
    <section className="glass card bot-extra">
      <div className="w-head">
        <span className="w-title">Valve Regional Standings</span>
        {vrs?.as_of && <span className="w-meta">as of {vrs.as_of}</span>}
      </div>
      {vrs?.teams && (
        <div className="kv-rows vrs-list">
          {vrs.teams.map((t, i) => (
            <div key={i} className="kv-row"><span className="mono">#{i + 1}</span><span>{t}</span></div>
          ))}
        </div>
      )}
      <div className="w-actions">
        <button className="tb-btn" disabled={load.isPending} onClick={() => load.mutate()}>
          <ListOrdered /> {load.isPending ? 'Fetching…' : vrs ? 'Refresh VRS list' : 'Show VRS list'}
        </button>
      </div>
      <p className="form-note t-dim">
        VRS = Valve Regional Standings (official ranking, refreshed ~weekly) — the only
        ranking the digest uses.
      </p>
    </section>
  );
}

// ── jellyfin: connection check ───────────────────────────────────────────────

export function JellyfinCheckCard() {
  const [result, setResult] = useState<{ text: string; ok: boolean } | null>(null);
  const check = useMutation({
    mutationFn: () => get<JellyfinCheck>('/api/jellyfin/check', 20_000),
    onSuccess: (d) => {
      if (d?.ok) {
        setResult({
          ok: true,
          text: `Connected ✓ — ${d.server_name ?? 'Jellyfin'}${d.version ? ` (v${d.version})` : ''}`,
        });
      } else {
        setResult({ ok: false, text: d?.error ?? 'Check failed — the bot reported an error.' });
      }
    },
    onError: (e) => setResult({ ok: false, text: extraErrorMessage(e, 'Check failed.') }),
  });

  return (
    <section className="glass card bot-extra">
      <div className="w-head">
        <span className="w-title">Server connection</span>
      </div>
      {result && <p className={result.ok ? 't-dim' : 't-crit'}>{result.text}</p>}
      <div className="w-actions">
        <button className="tb-btn" disabled={check.isPending} onClick={() => check.mutate()}>
          <Plug /> {check.isPending ? 'Checking…' : 'Test connection'}
        </button>
      </div>
      <p className="form-note t-dim">
        Probes the configured Jellyfin URL with the saved API key — save settings first if
        you just changed either.
      </p>
    </section>
  );
}
