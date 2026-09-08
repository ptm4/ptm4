// The service catalog with live health (backend/lib/services.js ⋈ probes ⋈ containers).
import { createQuery } from '@tanstack/svelte-query';
import { get } from './client';
import { LINK_GROUPS } from '$lib/links';

export interface Service {
  id: string;
  label: string;
  url: string;
  icon: string;
  category: string;
  host: string | null;
  container?: string;
  probe?: string;
  fav?: boolean;
  internal?: boolean;
  internalPage?: string;
  description?: string;
  state: 'up' | 'down' | 'unknown';
  probe_status: number | null;
  probe_error: string | null;
  container_state: string | null;
  update_available: boolean;
}

export interface ServicesResp { services: Service[]; categories: string[]; checked_at: string | null }

export const useServices = () => createQuery(() => ({
  queryKey: ['services'],
  queryFn: () => get<ServicesResp>('/api/services', 15_000),
  refetchInterval: 60_000,
  retry: 0,
}));

// A v2 backend has no /api/services: rebuild a usable catalog from the static link
// groups so the Launchpad still renders (without health).
export function fallbackServices(): ServicesResp {
  const services: Service[] = [];
  for (const g of LINK_GROUPS) {
    for (const l of g.links) {
      services.push({
        id: l.label.toLowerCase().replace(/[^a-z0-9]+/g, '-'), label: l.label, url: l.url, icon: l.icon,
        category: g.group === 'Library management' ? 'Library' : g.group === 'This dashboard' ? 'Dashboard' : g.group,
        host: null, probe: l.checkOrigin, fav: l.fav, internal: !l.checkOrigin && l.url.startsWith('/'),
        state: 'unknown', probe_status: null, probe_error: null, container_state: null, update_available: false,
      });
    }
  }
  return { services, categories: [...new Set(services.map((s) => s.category))], checked_at: null };
}
