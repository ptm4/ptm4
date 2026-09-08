// v1 was a hash-router (#home, #cockpit, #weather…). Every old bookmark and
// muscle-memory URL must keep working: on boot, translate the hash to a v2 path
// before the router renders.

const MAP: Record<string, string> = {
  home: '/',
  cockpit: '/cockpit',
  logs: '/logs',
  reports: '/reports',
  security: '/security',
  bots: '/bots',
  weather: '/bots?tab=weather',
  healthdigest: '/bots?tab=healthdigest',
  jellyfin: '/bots?tab=jellyfin',
  sports: '/bots?tab=sports',
  hltv: '/bots?tab=hltv',
  leetify: '/leetify',
  llm: '/llm',
  links: '/links',
};

export function redirectLegacyHash(): void {
  const hash = window.location.hash.replace(/^#/, '');
  if (!hash) return;
  const target = MAP[hash];
  if (target && window.location.pathname === '/') {
    window.history.replaceState(null, '', target);
  }
}
