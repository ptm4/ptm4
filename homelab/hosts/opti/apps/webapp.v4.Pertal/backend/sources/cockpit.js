'use strict';
const { HOSTS } = require('../lib/hosts');
const SAFE_PATH = /^[a-z0-9-]+(?:\/[a-z0-9-]+){0,3}$/;
const object = (value) => value && typeof value === 'object' && !Array.isArray(value);

function parseManifests(manifests) {
  if (!object(manifests) || !object(manifests.shell) ||
      !['system', 'systemd'].some((name) => object(manifests[name]))) {
    throw new Error('Cockpit did not return shell and system manifests');
  }
  const packages = Object.keys(manifests).filter((name) => /^[a-z0-9-]+$/.test(name));
  const pages = new Map();
  for (const name of packages) {
    const manifest = manifests[name];
    if (!object(manifest)) continue;
    for (const section of ['menu', 'tools', 'dashboard']) {
      if (!object(manifest[section])) continue;
      for (const [key, entry] of Object.entries(manifest[section])) {
        if (!object(entry) || typeof entry.label !== 'string' || !entry.label.trim()) continue;
        const path = key === 'index' ? name : `${name}/${key}`;
        if (!SAFE_PATH.test(path)) continue;
        pages.set(path, { label: entry.label.slice(0, 120), path });
      }
    }
  }
  if (packages.includes('metrics')) pages.set('metrics', { label: 'Metrics', path: 'metrics' });
  return { packages, pages: [...pages.values()] };
}

function registerCockpitSources(snapshots, hosts = HOSTS) {
  for (const host of hosts.filter((h) => h.console)) {
    snapshots.register({
      key: `cockpit:${host.id}`, group: 'cockpit', label: `Console · ${host.label}`,
      intervalMs: 60_000, timeoutMs: 5000, staleAfterMs: 5 * 60_000,
      fetch: async ({ signal }) => {
        const url = `${host.console.upstream}${host.console.root}/cockpit/@localhost/manifests.json`;
        const response = await fetch(url, { signal, redirect: 'error' });
        if (!response.ok) throw new Error(`Cockpit answered HTTP ${response.status}`);
        const body = await response.text();
        if (body.length > 1024 * 1024) throw new Error('Cockpit manifests are too large');
        let manifests;
        try { manifests = JSON.parse(body); } catch { throw new Error('Cockpit did not return JSON manifests'); }
        return parseManifests(manifests);
      },
    });
  }
}

module.exports = { registerCockpitSources, parseManifests };
