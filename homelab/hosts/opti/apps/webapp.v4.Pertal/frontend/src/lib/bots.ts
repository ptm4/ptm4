// The Discord bot fleet: five bots that share one control API (status / config / send /
// preview), so the only real difference is which config fields each has. Ported from
// v3.Fable's $lib/bots.ts; the backend is routes/bots.js (same /api/<bot>/* paths).
//
// Fields not listed (locations, witty_names, teams…) belong to structured editors, and
// `passthrough` names config keys the form doesn't model, so a save never drops them.
import { ApiError } from './api';

export type BotFieldType = 'time' | 'text' | 'password' | 'number' | 'boolean' | 'select';
export interface BotField {
  key: string; label: string; type: BotFieldType; help?: string;
  choices?: { value: string; label: string }[]; placeholder?: string;
}
export type BotExtra = 'geocode' | 'witty' | 'teams' | 'vrs' | 'jellyfin-check';
export interface BotDef {
  id: string; label: string; icon: string; container: string;
  fields: BotField[]; passthrough: string[]; extras?: BotExtra[];
}

const COMMON: BotField[] = [
  { key: 'post_time', label: 'Post time', type: 'time' },
  { key: 'message', label: 'Message', type: 'text', placeholder: 'Text above the embed' },
  { key: 'webhook_url', label: 'Webhook URL', type: 'password', help: 'Discord webhook; stored by the bot' },
];

export const BOTS: BotDef[] = [
  {
    id: 'weather', label: 'Weather', icon: 'cloud-sun', container: 'discord-weather',
    fields: [
      // posts as Weather-Bot; the webhook is only a fallback, so it isn't edited here
      ...COMMON.filter((f) => f.key !== 'webhook_url'),
      { key: 'channel_id', label: 'Channel ID', type: 'text', help: 'Where Weather-Bot posts (right-click the channel, Copy Channel ID)' },
      { key: 'witty_enabled', label: 'Witty messages', type: 'boolean', help: 'Persona line in the daily post' },
    ],
    passthrough: ['timezone'], extras: ['geocode', 'witty'],
  },
  {
    id: 'healthdigest', label: 'Health', icon: 'heart-pulse', container: 'discord-healthdigest',
    fields: [
      ...COMMON,
      { key: 'post_mode', label: 'Post mode', type: 'select', choices: [
        { value: 'always', label: 'Always' }, { value: 'alerts_only', label: 'Only when there are alerts' },
      ] },
      { key: 'top_blocked_count', label: 'Top blocked domains', type: 'number' },
      { key: 'request_fresh_report', label: 'Request a fresh doctor run', type: 'boolean', help: 'Slower (up to ~90s) but never posts stale numbers' },
      { key: 'pihole_password', label: 'Pi-hole password', type: 'password' },
    ],
    passthrough: ['timezone'],
  },
  {
    id: 'jellyfin', label: 'Jellyfin', icon: 'clapperboard', container: 'discord-jellyfin',
    fields: [
      ...COMMON,
      { key: 'jellyfin_url', label: 'Jellyfin URL', type: 'text' },
      { key: 'api_key', label: 'API key', type: 'password' },
      { key: 'max_items', label: 'Max items', type: 'number' },
      { key: 'post_when_empty', label: 'Post when nothing is new', type: 'boolean' },
    ],
    passthrough: ['timezone'], extras: ['jellyfin-check'],
  },
  {
    id: 'sports', label: 'Sports', icon: 'trophy', container: 'discord-sports',
    fields: [...COMMON], passthrough: ['timezone', 'leagues'], extras: ['teams'],
  },
  {
    // The only bot that posts more than once a day: a list of times, sent back as the
    // "00:00,07:00" string the bot accepts.
    id: 'hltv', label: 'HLTV', icon: 'crosshair', container: 'discord-hltv',
    fields: [
      { key: 'post_times', label: 'Post times', type: 'text', placeholder: '00:00, 07:00, 18:00', help: 'Comma-separated HH:MM (24h), one post per slot' },
      ...COMMON.filter((f) => f.key !== 'post_time'),
      { key: 'vrs_top_n', label: 'VRS top N', type: 'number' },
      { key: 'min_stars', label: 'Min HLTV stars', type: 'number', help: '0 to 5; 0 disables the star filter' },
      { key: 'post_when_empty', label: 'Post when no matches', type: 'boolean' },
      { key: 'alert_on_failure', label: 'Alert on failure', type: 'boolean', help: 'Post a warning if HLTV stays unreachable for 2h' },
    ],
    passthrough: ['timezone'], extras: ['vrs'],
  },
];
export const BOT_BY_ID: Record<string, BotDef> = Object.fromEntries(BOTS.map((b) => [b.id, b]));

export type BotConfig = Record<string, unknown>;
export interface BotStatus { enabled?: boolean; next_post_at?: string | null; last_post_at?: string | null; last_status?: string | null }
export interface DiscordEmbed { title?: string; description?: string; fields?: { name: string; value: string; inline?: boolean }[]; footer?: { text: string } }
export interface BotPreview { payload?: { content?: string; username?: string; embeds?: DiscordEmbed[] }; failed?: string[] }
export interface WeatherLocation { name: string; lat: number; lon: number }
export interface GeocodeResult { name: string; admin1?: string; country?: string; lat: number; lon: number }
export interface WittyStatus {
  available?: boolean; reason?: string; enabled?: boolean; remaining?: number; cycle?: number;
  next_generic?: string | null; last_posted?: { at?: number; text?: string } | null; pool_size?: number;
}
export interface WittyReroll { ok?: boolean; next?: string | null; remaining?: number; note?: string; error?: string }
export interface SportsTeam { name: string; league?: string; abbrev?: string; [k: string]: unknown }
export interface VrsList { as_of?: string; teams?: string[] }
export interface JellyfinCheck { ok?: boolean; server_name?: string; version?: string; error?: string }

// Bot proxies legitimately 502 when a container is down: no retries, just a clear error.
export async function botCall<T>(path: string, init: RequestInit & { timeoutMs?: number } = {}): Promise<T> {
  const { timeoutMs = 10_000, ...rest } = init;
  const res = await fetch(path, {
    ...rest,
    headers: { 'Content-Type': 'application/json', ...(rest.headers || {}) },
    signal: AbortSignal.timeout(timeoutMs),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, body?.error || body?.detail || `HTTP ${res.status}`);
  return body as T;
}

export function botError(bot: BotDef, e: unknown): string {
  const err = e as ApiError;
  if (err?.status === 502) return `${bot.container} is not answering. Check its container on the Resources page.`;
  if (err?.status === 400) return `Rejected: ${err.message}`;
  return err?.message ?? 'Request failed.';
}
