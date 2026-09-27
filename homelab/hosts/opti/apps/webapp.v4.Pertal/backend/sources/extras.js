// Status-page extras: weather, NBA, calendar (CS2 comes from sources/streams.js's
// hltv:day snapshot). Same snapshot rules as everything
// else — polled in the background, never fetched inside a request.
//
// Settings come from the Discord bots themselves (their GET /config on the internal
// compose network), so the location and teams Peter set for the bots are the ones shown
// here. Outside that network (dev on the workstation) the bots' defaults are used.
'use strict';
const { eventsBetween, zonedToUtc } = require('../lib/ics');

const TZ = 'America/New_York';
const BOT = {
  weather: process.env.BOT_WEATHER_URL || 'http://discord-weather:8080',
  sports: process.env.BOT_SPORTS_URL || 'http://discord-sports:8080',
};
const CALENDARS = (process.env.PERTAL_CALENDAR_ICS || '').split(/\s*,\s*/).filter(Boolean);

const DEFAULT_LOCATION = { name: 'Bellerose, NY', lat: 40.7328, lon: -73.7178 };
const DEFAULT_TEAMS = [{ league: 'nba', sport: 'basketball', id: '18', abbrev: 'NY', name: 'New York Knicks' }];

async function json(url, signal, timeoutMs = 8000) {
  const res = await fetch(url, { signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs) });
  if (!res.ok) throw new Error(`${new URL(url).host}: HTTP ${res.status}`);
  return res.json();
}

async function botConfig(base, signal) {
  try { return await json(`${base}/config`, signal, 3000); } catch (_) { return null; }
}

// YYYYMMDD for "today" in New York (ESPN's scoreboard day).
const nyDate = (t = Date.now()) =>
  new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' })
    .format(new Date(t)).replaceAll('-', '');

const WMO = {
  0: 'Clear', 1: 'Mostly clear', 2: 'Partly cloudy', 3: 'Overcast', 45: 'Fog', 48: 'Rime fog',
  51: 'Light drizzle', 53: 'Drizzle', 55: 'Heavy drizzle', 56: 'Freezing drizzle', 57: 'Freezing drizzle',
  61: 'Light rain', 63: 'Rain', 65: 'Heavy rain', 66: 'Freezing rain', 67: 'Freezing rain',
  71: 'Light snow', 73: 'Snow', 75: 'Heavy snow', 77: 'Snow grains', 80: 'Showers', 81: 'Showers',
  82: 'Violent showers', 85: 'Snow showers', 86: 'Snow showers', 95: 'Thunderstorm', 96: 'Thunderstorm, hail', 99: 'Thunderstorm, hail',
};

async function fetchWeather({ signal }) {
  const cfg = await botConfig(BOT.weather, signal);
  const loc = cfg?.config?.locations?.[0] ?? cfg?.locations?.[0] ?? DEFAULT_LOCATION;
  const q = new URLSearchParams({
    latitude: loc.lat, longitude: loc.lon, timezone: TZ, forecast_days: '2',
    temperature_unit: 'fahrenheit', wind_speed_unit: 'mph', precipitation_unit: 'inch',
    current: 'temperature_2m,apparent_temperature,weather_code,wind_speed_10m,is_day',
    daily: 'temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,sunrise,sunset',
    hourly: 'temperature_2m,precipitation_probability,weather_code',
  });
  const d = await json(`https://api.open-meteo.com/v1/forecast?${q}`, signal);
  const nowHour = d.current.time.slice(0, 13);
  const start = Math.max(0, d.hourly.time.findIndex((t) => t.slice(0, 13) === nowHour));
  return {
    location: loc.name,
    source: cfg ? 'discord-weather config' : 'default location',
    now: {
      temp: Math.round(d.current.temperature_2m), feels: Math.round(d.current.apparent_temperature),
      code: d.current.weather_code, text: WMO[d.current.weather_code] ?? '—',
      wind_mph: Math.round(d.current.wind_speed_10m), is_day: !!d.current.is_day,
    },
    today: {
      hi: Math.round(d.daily.temperature_2m_max[0]), lo: Math.round(d.daily.temperature_2m_min[0]),
      rain_pct: d.daily.precipitation_probability_max[0], code: d.daily.weather_code[0],
      text: WMO[d.daily.weather_code[0]] ?? '—', sunrise: d.daily.sunrise[0], sunset: d.daily.sunset[0],
    },
    tomorrow: {
      hi: Math.round(d.daily.temperature_2m_max[1]), lo: Math.round(d.daily.temperature_2m_min[1]),
      rain_pct: d.daily.precipitation_probability_max[1], text: WMO[d.daily.weather_code[1]] ?? '—',
    },
    hours: d.hourly.time.slice(start, start + 12).map((t, i) => ({
      time: t, temp: Math.round(d.hourly.temperature_2m[start + i]),
      rain_pct: d.hourly.precipitation_probability[start + i], code: d.hourly.weather_code[start + i],
    })),
  };
}

async function fetchNba({ signal }) {
  const cfg = await botConfig(BOT.sports, signal);
  const teams = (cfg?.config?.teams ?? cfg?.teams ?? DEFAULT_TEAMS).filter((t) => t.league === 'nba');
  const ids = new Set(teams.map((t) => String(t.id)));
  const board = await json(`https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=${nyDate()}`, signal);
  const games = (board.events || []).map((e) => {
    const c = e.competitions?.[0] || {};
    const side = (ha) => {
      const x = (c.competitors || []).find((k) => k.homeAway === ha) || {};
      return { id: String(x.team?.id ?? ''), abbrev: x.team?.abbreviation ?? '?', name: x.team?.displayName ?? '?', score: x.score ?? null, winner: !!x.winner };
    };
    return {
      id: e.id, start: e.date, state: e.status?.type?.state ?? 'pre', // pre | in | post
      detail: e.status?.type?.shortDetail ?? '', home: side('home'), away: side('away'),
      mine: [side('home').id, side('away').id].some((id) => ids.has(id)),
    };
  }).sort((a, b) => Number(b.mine) - Number(a.mine) || a.start.localeCompare(b.start));

  // Nothing today for my team → its next scheduled game.
  let next = null;
  if (!games.some((g) => g.mine) && teams[0]) {
    try {
      const s = await json(`https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/${teams[0].id}/schedule`, signal);
      const upcoming = (s.events || []).find((e) => Date.parse(e.date) > Date.now());
      if (upcoming) next = { start: upcoming.date, name: upcoming.shortName ?? upcoming.name };
    } catch (_) { /* optional */ }
  }
  return { teams: teams.map((t) => t.name), source: cfg ? 'discord-sports config' : 'default team', games, next };
}

async function fetchCalendar({ signal }) {
  const now = Date.now();
  const [y, m, d] = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' })
    .format(new Date(now)).split('-').map(Number);
  const from = zonedToUtc(y, m, d, 0, 0, 0, TZ); // today 00:00 in New York
  const to = from + 3 * 86_400_000;              // today, tomorrow, the day after
  const all = [];
  for (const url of CALENDARS) {
    const res = await fetch(url, { signal: AbortSignal.any([signal, AbortSignal.timeout(10_000)]) });
    if (!res.ok) throw new Error(`calendar: HTTP ${res.status}`);
    all.push(...eventsBetween(await res.text(), from, to, TZ));
  }
  return { events: all.sort((a, b) => a.start.localeCompare(b.start)).slice(0, 20) };
}

function registerExtrasSources(snapshots) {
  snapshots.register({ key: 'extras:weather', group: 'extras', label: 'weather', intervalMs: 15 * 60_000, timeoutMs: 12_000, staleAfterMs: 60 * 60_000, fetch: fetchWeather });
  snapshots.register({ key: 'extras:nba', group: 'extras', label: 'NBA scores', intervalMs: 3 * 60_000, timeoutMs: 12_000, staleAfterMs: 20 * 60_000, fetch: fetchNba });
  if (CALENDARS.length) {
    snapshots.register({ key: 'extras:calendar', group: 'extras', label: 'calendar', intervalMs: 15 * 60_000, timeoutMs: 15_000, staleAfterMs: 60 * 60_000, fetch: fetchCalendar });
  }
}

module.exports = { registerExtrasSources, CALENDARS };
