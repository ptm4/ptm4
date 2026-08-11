import { useLocation } from 'react-router-dom';
import { Search, SunMoon, History } from 'lucide-react';
import { toggleTheme } from '../lib/theme';
import { useUi } from '../lib/ui-store';
import { NotificationBell } from './Notifications';

const TITLES: Record<string, string> = {
  '/': 'Home',
  '/dashboard': 'Dashboard',
  '/cockpit': 'Cockpit',
  '/reports': 'Reports',
  '/security': 'Security',
  '/bots': 'Discord bots',
  '/leetify': 'CS2 / Leetify',
  '/llm': 'Local LLM',
  '/links': 'Quick links',
  '/logs': 'Logs',
  '/trends': 'Trends',
  '/updates': 'Updates',
  '/settings': 'Settings',
};

export function Topbar() {
  const { pathname } = useLocation();
  const setCmdkOpen = useUi((s) => s.setCmdkOpen);
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
  // Pages with their own hero title (boards, containers, pihole) would double up.
  const hasOwnTitle = pathname === '/' || pathname === '/dashboard'
    || pathname.startsWith('/b/') || pathname === '/containers' || pathname === '/pihole';

  return (
    <header className="topbar glass">
      <h1 className={hasOwnTitle ? 't-dim topbar-quiet' : ''}>
        {hasOwnTitle ? 'Pert’s Pocket' : (TITLES[pathname] ?? 'Pert’s Pocket')}
      </h1>
      <div className="spacer" />
      <button className="tb-btn" onClick={() => setCmdkOpen(true)}>
        <Search aria-hidden /> Search <kbd>{isMac ? '⌘' : 'Ctrl'} K</kbd>
      </button>
      <NotificationBell />
      <button className="tb-btn" onClick={() => toggleTheme()} title="Toggle theme">
        <SunMoon aria-hidden /> Theme
      </button>
      <a className="tb-btn" href="/legacy/" title="The pre-redesign dashboard, unchanged">
        <History aria-hidden /> Legacy UI
      </a>
    </header>
  );
}
