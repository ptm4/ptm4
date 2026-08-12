// The bot registry — the dev-hat consolidation from the redesign plan. v1 had five
// near-identical page renderers and five backend proxy modules; the API contract is
// identical across bots (status/config/send/preview), so the only real difference
// is which config fields each one has. Declaring those here means adding bot #6 is
// a table entry, not a page.
//
// Field types map to the generic form renderer in pages/Bots.tsx. Fields NOT listed
// here (locations, witty_names, teams…) are structured editors that stay untouched
// on save — `passthrough` names them so a save never drops them.

export type BotFieldType = 'time' | 'text' | 'password' | 'number' | 'boolean' | 'select';

export interface BotField {
  key: string;
  label: string;
  type: BotFieldType;
  help?: string;
  choices?: { value: string; label: string }[];
  placeholder?: string;
}

export interface BotDef {
  id: string;             // API prefix: /api/<id>/…
  label: string;
  icon: string;           // emoji — these are the bots' own identity in Discord
  container: string;      // for the "check docker ps" error message
  fields: BotField[];
  passthrough: string[];  // config keys preserved verbatim across a save
  extras?: ('geocode' | 'witty' | 'teams' | 'vrs' | 'jellyfin-check')[];
}

const COMMON: BotField[] = [
  { key: 'post_time', label: 'Post time', type: 'time' },
  { key: 'message', label: 'Message', type: 'text', placeholder: 'Text above the embed' },
  { key: 'webhook_url', label: 'Webhook URL', type: 'password', help: 'Discord webhook; stored by the bot' },
];

export const BOTS: BotDef[] = [
  {
    id: 'weather',
    label: 'Weather',
    icon: '🌤️',
    container: 'discord-weather',
    fields: [
      ...COMMON,
      { key: 'witty_enabled', label: 'Witty messages', type: 'boolean', help: 'Madlibs roast line in the daily post' },
    ],
    passthrough: ['locations', 'witty_names', 'timezone'],
    extras: ['geocode', 'witty'],
  },
  {
    id: 'healthdigest',
    label: 'Health',
    icon: '🩺',
    container: 'discord-healthdigest',
    fields: [
      ...COMMON,
      { key: 'post_mode', label: 'Post mode', type: 'select', choices: [
        { value: 'embed', label: 'Embed' }, { value: 'text', label: 'Plain text' },
      ] },
      { key: 'top_blocked_count', label: 'Top blocked domains', type: 'number' },
      { key: 'request_fresh_report', label: 'Request a fresh doctor run', type: 'boolean',
        help: 'Slower (up to ~90s) but never posts stale numbers' },
      { key: 'pihole_password', label: 'Pi-hole password', type: 'password' },
    ],
    passthrough: ['timezone'],
  },
  {
    id: 'jellyfin',
    label: 'Jellyfin',
    icon: '🎬',
    container: 'discord-jellyfin',
    fields: [
      ...COMMON,
      { key: 'jellyfin_url', label: 'Jellyfin URL', type: 'text' },
      { key: 'api_key', label: 'API key', type: 'password' },
      { key: 'max_items', label: 'Max items', type: 'number' },
      { key: 'post_when_empty', label: 'Post when nothing is new', type: 'boolean' },
    ],
    passthrough: ['timezone'],
    extras: ['jellyfin-check'],
  },
  {
    id: 'sports',
    label: 'Sports',
    icon: '🏟️',
    container: 'discord-sports',
    fields: [...COMMON],
    passthrough: ['timezone', 'teams', 'leagues'],
    extras: ['teams'],
  },
  {
    // The only bot that posts more than once a day, so it takes a list of times
    // instead of COMMON's single `post_time` picker. The generic renderer shows a
    // list as "00:00,07:00" and the bot accepts that string back verbatim.
    id: 'hltv',
    label: 'HLTV',
    icon: '🎯',
    container: 'discord-hltv',
    fields: [
      { key: 'post_times', label: 'Post times', type: 'text', placeholder: '00:00, 07:00, 18:00',
        help: 'Comma-separated HH:MM (24h) — one post per slot' },
      ...COMMON.filter((f) => f.key !== 'post_time'),
      { key: 'vrs_top_n', label: 'VRS top N', type: 'number' },
      { key: 'min_stars', label: 'Min HLTV stars', type: 'number', help: '0–5; 0 disables the star filter' },
      { key: 'post_when_empty', label: 'Post when no matches', type: 'boolean' },
      { key: 'alert_on_failure', label: 'Alert on failure', type: 'boolean',
        help: 'Post a warning if HLTV stays unreachable for 2h' },
    ],
    passthrough: ['timezone'],
    extras: ['vrs'],
  },
];

export const BOT_BY_ID = Object.fromEntries(BOTS.map((b) => [b.id, b]));

export interface BotStatus {
  enabled?: boolean;
  next_post_at?: string | null;
  last_post_at?: string | null;
  last_status?: string | null;
}

export type BotConfig = Record<string, unknown>;

export interface DiscordEmbed {
  title?: string;
  description?: string;
  fields?: { name: string; value: string; inline?: boolean }[];
  footer?: { text: string };
}

export interface BotPreview {
  payload?: { content?: string; username?: string; embeds?: DiscordEmbed[] };
  failed?: string[];
}
