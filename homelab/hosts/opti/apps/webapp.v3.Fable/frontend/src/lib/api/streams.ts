// Streams — stream-station control (proxied) and the v3 guide.
import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
import { get, post } from './client';

export type SlotState = 'idle' | 'starting' | 'running' | 'ended';

export interface Slot {
  slot: number;
  state: SlotState;
  type: 'channel' | 'url' | null;
  platform: string | null;
  channel: string | null;
  url: string | null;
  quality: string | null;
  profile: string | null;
  started_at: number | null;
  uptime_s: number | null;
  last_index_fetch_s: number | null;
  last_segment_age_s: number | null;
  error: string | null;
}

export interface StationStatus { version: string; idle_secs: number; profiles: string[]; slots: Slot[] }

export interface GuideChannel {
  platform: 'twitch' | 'youtube' | 'kick';
  channel: string;
  label: string;
  org?: string | null;
  group: string;
  group_label: string;
  /** the slot OUR station is playing this channel in — an observation, not a guess */
  watching_slot: number | null;
  /** how many of today's matches list this channel as their broadcast (not a live check) */
  listed_matches: number;
}

/** What stream-station should be asked to start. Built server-side from the URL
 *  HLTV attached to the match, so the browser never has to parse a broadcast link. */
export type WatchTarget =
  | { type: 'channel'; platform: string; channel: string }
  | { type: 'url'; url: string };

export interface GuideMatch {
  id?: string; url?: string; event?: string; stars?: number; bo?: string;
  team1?: string; team2?: string; start_unix?: number;
  /** 'unknown' when the feed is too stale to assert a match is live */
  status?: 'upcoming' | 'live' | 'finished' | 'unknown';
  score1?: number | null; score2?: number | null; winner?: string | null;
  maps?: { name?: string; s1?: number; s2?: number }[];
  stream?: { name?: string; url?: string } | null;
  /** Valve Regional Standings position, or null when the team is not in the list */
  rank1: number | null;
  rank2: number | null;
  top20: boolean;
  /** the EVENT NAME reads as a premier series — not a tier ruling */
  premier: boolean;
  /** only ever 'S', and only when the feed said so; never derived from stars */
  tier: 'S' | null;
  watch: WatchTarget | null;
  channel: { platform: string; channel: string; label: string } | null;
  stream_source: string | null;
  watching_slot: number | null;
}

export interface GuideEvent {
  event: string; premier: boolean;
  live: number; unknown: number; upcoming: number; finished: number;
  top20: number;
  channel: GuideMatch['channel']; stream_source: string | null;
}

export interface Guide {
  station: { ok: boolean; version?: string; idle_secs?: number; profiles?: string[]; slots: Slot[] };
  quality_default: string;
  channels: GuideChannel[];
  matches: GuideMatch[];
  events: GuideEvent[];
  vrs: { as_of: string | null; known: boolean; system: string; counted: number; top: string[]; error: string | null };
  hltv: { ok: boolean; stale: boolean; fetched_at: number | null; date: string | null; error: string | null };
  coverage: string;
  generated_at: string;
}

export const useStationStatus = (fast: () => boolean = () => false) => createQuery(() => ({
  queryKey: ['streams-status'],
  queryFn: () => get<StationStatus>('/api/streams/status', 12_000),
  refetchInterval: fast() ? 5_000 : 60_000,
  retry: 0,
}));

export const useGuide = () => createQuery(() => ({
  queryKey: ['streams-guide'],
  queryFn: () => get<Guide>('/api/streams/guide', 30_000),
  refetchInterval: 60_000,
  retry: 0,
}));

export interface WatchReq { platform?: string; channel?: string; url?: string; slot?: number; quality?: string; profile?: string }

export function useStreamActions() {
  const qc = useQueryClient();
  const done = () => { qc.invalidateQueries({ queryKey: ['streams-status'] }); qc.invalidateQueries({ queryKey: ['streams-guide'] }); };
  const watch = createMutation(() => ({
    mutationFn: (v: WatchReq) => post<{ ok: boolean; slot: number; state: string; reused?: boolean }>('/api/streams/watch', v, 20_000),
    onSuccess: done,
  }));
  const stop = createMutation(() => ({
    mutationFn: (slot: number) => post('/api/streams/stop', { slot }, 10_000),
    onSuccess: done,
  }));
  const keepalive = (slots: number[]) => post('/api/streams/keepalive', { slots }, 8_000).catch(() => {});
  return { watch, stop, keepalive };
}

export const hlsUrl = (slot: number) => `/hls/slot${slot}/index.m3u8`;
export const watchUrl = (platform: string, channel: string) =>
  platform === 'twitch' ? `https://www.twitch.tv/${channel}`
  : platform === 'youtube' ? `https://www.youtube.com/@${channel}/live`
  : platform === 'kick' ? `https://kick.com/${channel}` : '#';
