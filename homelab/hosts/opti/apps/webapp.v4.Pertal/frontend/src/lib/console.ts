export const CONSOLE_HOSTS = ['opti', 'rpi', 'noblenumbat'] as const;
export const consoleHost = (host: string): boolean => CONSOLE_HOSTS.some((id) => id === host);
export const consolePath = (path: string): string =>
  /^[a-z0-9-]+(?:\/[a-z0-9-]+){0,3}$/.test(path) ? path : 'system';
// A Pertal page (same tab). Same-origin apps nginx serves beside Pertal (/notes) open like any other app.
export const internalLink = (href: string): boolean => href.startsWith('/') && !href.startsWith('//') && !href.startsWith('/notes');
