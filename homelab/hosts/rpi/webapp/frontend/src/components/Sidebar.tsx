import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard, Grid2x2, SlidersHorizontal, FileText, Shield, ScrollText,
  Bot, Crosshair, BrainCircuit, Link2, Network, Workflow, ServerCog,
  ExternalLink, TrendingUp, Tv, Boxes, ShieldCheck, Database,
} from 'lucide-react';

// External = full page loads (legacy standalone pages + notes). They keep their
// original URLs until each is absorbed (P6) — see backend/plugins/static.js.
const EXTERNAL = [
  { href: '/architecture/', label: 'Architecture', icon: Network },
  { href: '/streams/', label: 'Streams', icon: Tv },
  { href: '/samba/', label: 'Samba', icon: ServerCog },
  { href: '/agentic/', label: 'Agentic', icon: Workflow },
  { href: '/agents/', label: 'Agents', icon: ServerCog },
  { href: '/notes/', label: 'Notes', icon: FileText },
];

function Item({ to, label, icon: Icon }: { to: string; label: string; icon: typeof LayoutDashboard }) {
  return (
    <NavLink to={to} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} end={to === '/'}>
      <Icon aria-hidden />
      {label}
    </NavLink>
  );
}

export function Sidebar() {
  return (
    <nav className="side glass" aria-label="Primary">
      <div className="side-brand">
        <img src="/favicon.svg" alt="" />
        Pert&apos;s Pocket
        <span className="tag">v2</span>
      </div>

      <div className="nav-group">
        <h3>Boards</h3>
        <Item to="/" label="Home" icon={LayoutDashboard} />
        <Item to="/dashboard" label="Dashboard" icon={Grid2x2} />
      </div>

      <div className="nav-group">
        <h3>Operations</h3>
        <Item to="/cockpit" label="Cockpit" icon={SlidersHorizontal} />
        <Item to="/containers" label="Containers" icon={Boxes} />
        <Item to="/pihole" label="Pi-hole" icon={ShieldCheck} />
        <Item to="/updates" label="Updates" icon={TrendingUp} />
        <Item to="/reports" label="Reports" icon={FileText} />
        <Item to="/security" label="Security" icon={Shield} />
        <Item to="/logs" label="Logs" icon={ScrollText} />
        <Item to="/trends" label="Trends" icon={TrendingUp} />
        <Item to="/data" label="Data" icon={Database} />
      </div>

      <div className="nav-group">
        <h3>Services</h3>
        <Item to="/bots" label="Discord bots" icon={Bot} />
        <Item to="/leetify" label="CS2 / Leetify" icon={Crosshair} />
        <Item to="/llm" label="Local LLM" icon={BrainCircuit} />
        <Item to="/links" label="Quick links" icon={Link2} />
      </div>

      <div className="nav-group">
        <h3>Pages</h3>
        {EXTERNAL.map(({ href, label, icon: Icon }) => (
          <a key={href} className="nav-link" href={href}>
            <Icon aria-hidden />
            {label}
            <ExternalLink className="ext" aria-hidden />
          </a>
        ))}
      </div>
    </nav>
  );
}
