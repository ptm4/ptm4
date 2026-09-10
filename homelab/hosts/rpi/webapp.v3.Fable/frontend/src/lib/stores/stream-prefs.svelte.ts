// Streams preferences that belong to this browser: starred channels, the channels you
// actually started recently, and the quality/latency you like. Kept local (not in
// /api/ui/settings) because they describe how YOU watch on THIS device — the phone
// wants 720p on cellular while the desktop wants best.
import { browser } from '$app/environment';

const KEY = 'fable-stream-prefs-v1';
const MAX_RECENT = 8;

export interface RecentChannel { platform: string; channel: string; label: string }

interface Prefs {
  favorites: string[];          // "platform/channel"
  recent: RecentChannel[];
  quality: string;
  profile: string;
}

const DEFAULTS: Prefs = {
  favorites: ['twitch/blastpremier', 'twitch/eslcs', 'twitch/ohnepixel'],
  recent: [],
  quality: '',
  profile: 'low-latency',
};

export const channelKey = (c: { platform: string; channel: string }) => `${c.platform}/${c.channel.toLowerCase()}`;

function read(): Prefs {
  if (!browser) return { ...DEFAULTS };
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || 'null');
    if (!raw || !Array.isArray(raw.favorites) || !Array.isArray(raw.recent)) return { ...DEFAULTS };
    return { ...DEFAULTS, ...raw };
  } catch { return { ...DEFAULTS }; }
}

let prefs = $state<Prefs>(read());
let unavailable = $state(false);

function persist() {
  if (!browser) return;
  try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { unavailable = true; }
}

export const streamPrefs = {
  get favorites() { return prefs.favorites; },
  get recent() { return prefs.recent; },
  get quality() { return prefs.quality; },
  get profile() { return prefs.profile; },
  /** true once a write failed — private mode, or storage disabled */
  get unavailable() { return unavailable; },

  isFavorite(c: { platform: string; channel: string }) { return prefs.favorites.includes(channelKey(c)); },
  toggleFavorite(c: { platform: string; channel: string }) {
    const k = channelKey(c);
    prefs.favorites = prefs.favorites.includes(k) ? prefs.favorites.filter((x) => x !== k) : [...prefs.favorites, k];
    persist();
  },
  /** called after a successful start, so Recent reflects what actually played */
  remember(c: RecentChannel) {
    prefs.recent = [c, ...prefs.recent.filter((x) => channelKey(x) !== channelKey(c))].slice(0, MAX_RECENT);
    persist();
  },
  setQuality(q: string) { prefs.quality = q; persist(); },
  setProfile(p: string) { prefs.profile = p; persist(); },
};
