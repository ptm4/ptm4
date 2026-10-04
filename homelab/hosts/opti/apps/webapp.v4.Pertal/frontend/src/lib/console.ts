export const CONSOLE_HOSTS = ['opti', 'rpi', 'noblenumbat'] as const;
export const consoleHost = (host: string): boolean => CONSOLE_HOSTS.some((id) => id === host);
export const consolePath = (path: string): string =>
  /^[a-z0-9-]+(?:\/[a-z0-9-]+){0,3}$/.test(path) ? path : 'system';
export const internalLink = (href: string): boolean => href.startsWith('/') && !href.startsWith('//');
