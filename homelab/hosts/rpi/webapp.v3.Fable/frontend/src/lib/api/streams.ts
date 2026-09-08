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
  watching_slot: number | null;
  on_air: boolean;
  scheduled: number;
}

export interface GuideMatch {
  id?: string; url?: string; event?: string; stars?: number; bo?: string;
  team1?: string; team2?: string; start_unix?: number;
  status?: 'upcoming' | 'live' | 'finished';
  score1?: number | null; score2?: number | null; winner?: string | null;
  maps?: { name?: string; s1?: number; s2?: number }[];
  stream?: { name?: string; url?: string } | null;
  tier: 'S' | 'A' | 'B';
  top20: string[];
  organizer: string | null;
  channel: { platform: string; channel: string; label: string } | null;
  watching_slot: number | null;
}

export interface GuideEvent {
  event: string; tier: 'S' | 'A' | 'B'; live: number; upcoming: number; finished: number;
  organizer: string | null; channel: GuideMatch['channel']; top20: string[];
}

export interface Guide {
  station: { ok: boolean; version?: string; idle_secs?: number; profiles?: string[]; slots: Slot[] };
  quality_default: string;
  channels: GuideChannel[];
  matches: GuideMatch[];
  events: GuideEvent[];
  vrs: { as_of: string | null; top: string[] };
  hltv: { ok: boolean; stale: boolean; fetched_at: number | null; date: string | null; error: string | null };
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
