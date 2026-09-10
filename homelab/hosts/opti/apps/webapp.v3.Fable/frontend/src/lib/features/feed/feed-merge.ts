// One stream from three sources: the activity read-model (reports, watchdog heals,
// backups, bot posts), open incidents, and homelab.db change events. Everything
// gets a category so the feed can be filtered, a tone so it can be scanned, and a
// day bucket so it can be read.
import type { ActivityEvent } from '$lib/api/types';
import type { ChangeEvent } from '$lib/api/fleet';
import type { Incident } from '$lib/api/incidents';
import { toneForSeverity, type Tone } from '$lib/format';

export type FeedCategory = 'health' | 'bots' | 'security' | 'changes' | 'updates' | 'backup' | 'vpn' | 'incident' | 'other';

export interface FeedItem {
  key: string;
  ts: string | null;
  kind: 'incident' | 'activity' | 'change';
  category: FeedCategory;
  tone: Tone | 'info';
  who: string;
  what: string;
  excerpt?: string;
  host: string | null;
  source: string;
  link?: string;
  incident?: Incident;
  change?: ChangeEvent;
}

export const CATEGORY_LABEL: Record<FeedCategory, string> = {
  incident: 'Needs action', health: 'Health', bots: 'Bots', security: 'Security',
  changes: 'Changes', updates: 'Updates', backup: 'Backups', vpn: 'VPN', other: 'Other',
};

export function categoryFor(source: string): FeedCategory {
  const s = source.toLowerCase();
  if (/^(homelab-doctor|hardware|software|network)/.test(s)) return 'health';
  if (/^discord-|bot$/.test(s)) return 'bots';
  if (/journal|persistence|security|linkedin|arp|audit/.test(s)) return 'security';
  if (/vpn/.test(s)) return 'vpn';
  if (/autoupdate|update/.test(s)) return 'updates';
  if (/coldcopy|backup|attic/.test(s)) return 'backup';
  return 'other';
}

export const AVATAR: Record<FeedCategory, string> = {
  incident: '!', health: 'D', bots: 'B', security: 'S', changes: 'H', updates: 'U', backup: 'A', vpn: 'V', other: '·',
};

const t = (iso: string | null | undefined) => Date.parse(iso || '') || 0;

export function mergeFeed(
  activity: ActivityEvent[] | undefined,
  incidents: Incident[] | undefined,
  changes: ChangeEvent[] | undefined,
): FeedItem[] {
  const out: FeedItem[] = [];

  for (const inc of incidents ?? []) {
    if (inc.status === 'acked') continue;
    out.push({
      key: `inc:${inc.id}`,
      ts: inc.last_seen,
      kind: 'incident',
      category: 'incident',
      tone: inc.status === 'muted' ? 'info' : inc.severity === 'crit' ? 'crit' : 'warn',
      who: `Incident ${inc.id.slice(0, 6)}`,
      what: inc.title,
      excerpt: inc.items.slice(0, 3).map((i) => `${i.source}: ${i.message}`).join(' · ') + (inc.count > 3 ? ` · +${inc.count - 3}` : ''),
      host: inc.host,
      source: inc.sources.join(', '),
      link: `/feed?view=incidents#${inc.id}`,
      incident: inc,
    });
  }

  for (const e of activity ?? []) {
    out.push({
      key: `act:${e.ts}|${e.source}|${e.host}|${e.message}`,
      ts: e.ts,
      kind: 'activity',
      category: categoryFor(e.source),
      tone: toneForSeverity(e.severity) || 'info',
      who: e.source,
      what: e.message,
      host: e.host,
      source: e.source,
    });
  }

  for (const c of changes ?? []) {
    const verb = c.change === 'added' ? 'appeared' : c.change === 'removed' ? 'vanished' : 'changed';
    out.push({
      key: `chg:${c.at}|${c.host}|${c.kind}|${c.key}`,
      ts: c.at,
      kind: 'change',
      category: 'changes',
      tone: c.change === 'removed' ? 'crit' : c.change === 'added' ? 'ok' : 'warn',
      who: 'homelab-db',
      what: `${c.kind} ${c.key} ${verb} on ${c.host}`,
      host: c.host,
      source: 'homelab-db',
      change: c,
    });
  }

  out.sort((a, b) => t(b.ts) - t(a.ts));
  return out;
}

// "Today" / "Yesterday" / weekday+date labels for the day dividers.
export function dayLabel(iso: string | null): string {
  if (!iso) return 'Undated';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'Undated';
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const day = new Date(d); day.setHours(0, 0, 0, 0);
  const diff = Math.round((today.getTime() - day.getTime()) / 86400_000);
  if (diff === 0) return 'Today';
  if (diff === 1) return 'Yesterday';
  if (diff < 7) return d.toLocaleDateString(undefined, { weekday: 'long' });
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

export function timeLabel(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
}
