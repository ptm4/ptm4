// Quick links as a Homarr-style icon grid: real service icons, health dot per
// app (server-side /api/linkcheck probes — the browser can't probe http from an
// https page), type-to-filter.
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get } from '../lib/api';
import { LINK_GROUPS, iconUrl, isExternal } from '../lib/links';

interface LinkcheckResp {
  origins: Record<string, { up: boolean; status?: number; error?: string }>;
}

export default function LinksPage() {
  const [filter, setFilter] = useState('');

  const check = useQuery({
    queryKey: ['linkcheck'],
    queryFn: () => get<LinkcheckResp>('/api/linkcheck', 15_000),
    refetchInterval: 30_000,
  });

  const groups = useMemo(() => {
    const f = filter.trim().toLowerCase();
    if (!f) return LINK_GROUPS;
    return LINK_GROUPS
      .map((g) => ({ ...g, links: g.links.filter((l) => l.label.toLowerCase().includes(f)) }))
      .filter((g) => g.links.length > 0);
  }, [filter]);

  return (
    <div className="links-page">
      <input
        className="links-filter glass"
        placeholder="Filter services…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        autoFocus={window.innerWidth > 860 /* v1 B11: no autofocus keyboard pop on mobile */}
      />

      {groups.map((g) => (
        <section key={g.group} className="links-group">
          <h2>{g.group}</h2>
          <div className="links-grid">
            {g.links.map((l) => {
              const probe = l.checkOrigin ? check.data?.origins[l.checkOrigin] : undefined;
              const state = !l.checkOrigin ? 'none' : probe == null ? 'unknown' : probe.up ? 'ok' : 'crit';
              return (
                <a
                  key={l.label}
                  className="app-tile glass"
                  href={l.url}
                  target={isExternal(l.url) ? '_blank' : undefined}
                  rel={isExternal(l.url) ? 'noreferrer' : undefined}
                  title={probe && !probe.up ? `down: ${probe.error ?? 'no response'}` : l.label}
                >
                  <img src={iconUrl(l.icon)} alt="" loading="lazy" />
                  <span className="app-label">{l.label}</span>
                  {state !== 'none' && <span className="app-dot" data-s={state} />}
                </a>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
