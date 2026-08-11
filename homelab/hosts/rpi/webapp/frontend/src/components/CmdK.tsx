import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Command } from 'cmdk';
import {
  LayoutDashboard, SlidersHorizontal, FileText, Shield, Bot, Crosshair,
  BrainCircuit, Link2, ScrollText, Network, Tv, SunMoon, Stethoscope, RefreshCw,
  History, Boxes, ExternalLink,
} from 'lucide-react';
import { useUi } from '../lib/ui-store';
import { toggleTheme } from '../lib/theme';
import { post } from '../lib/api';
import { toast } from '../lib/toast';
import { useContainers } from '../lib/queries';
import { ALL_LINKS, iconUrl, isExternal } from '../lib/links';
import { Markdown } from './Markdown';
import { Modal } from './Modal';

const GOTO = [
  { path: '/', label: 'Home board', icon: LayoutDashboard },
  { path: '/dashboard', label: 'Dashboard board', icon: LayoutDashboard },
  { path: '/cockpit', label: 'Cockpit', icon: SlidersHorizontal },
  { path: '/containers', label: 'Containers', icon: Boxes },
  { path: '/pihole', label: 'Pi-hole', icon: Shield },
  { path: '/reports', label: 'Reports', icon: FileText },
  { path: '/security', label: 'Security', icon: Shield },
  { path: '/bots', label: 'Discord bots', icon: Bot },
  { path: '/leetify', label: 'CS2 / Leetify', icon: Crosshair },
  { path: '/llm', label: 'Local LLM', icon: BrainCircuit },
  { path: '/links', label: 'Quick links', icon: Link2 },
  { path: '/logs', label: 'Logs', icon: ScrollText },
];

const OPEN = [
  { href: '/architecture/', label: 'Architecture', icon: Network },
  { href: '/streams/', label: 'Streams', icon: Tv },
  { href: '/legacy/', label: 'Legacy UI', icon: History },
];

export function CmdK() {
  const open = useUi((s) => s.cmdkOpen);
  const setOpen = useUi((s) => s.setCmdkOpen);
  const navigate = useNavigate();
  const containers = useContainers();
  const [query, setQuery] = useState('');
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<{ q: string; a: string } | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpen(!useUi.getState().cmdkOpen);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setOpen]);

  if (!open) {
    // The answer modal outlives the palette — closing the palette to read it is the
    // natural gesture, and a 60s LLM round trip shouldn't be cancelled by that.
    return answer ? (
      <Modal open onClose={() => setAnswer(null)} title={`Ask the homelab — ${answer.q}`} wide>
        <Markdown source={answer.a} />
      </Modal>
    ) : null;
  }

  const run = (fn: () => void) => { setOpen(false); fn(); };

  // No palette match → offer the question to the runbook-grounded local LLM.
  const askHomelab = async (q: string) => {
    setAsking(true);
    toast('Asking the local LLM… this can take a minute on the phone', 'info');
    try {
      const d = await post<{ answer?: string; error?: string }>('/api/llama/ask', { question: q }, 185_000);
      setAnswer({ q, a: d.answer ?? d.error ?? '(no answer)' });
      setOpen(false);
    } catch (e) {
      toast(`Ask failed: ${(e as Error).message}`, 'crit');
    } finally {
      setAsking(false);
    }
  };

  const allContainers = (containers.data?.hosts ?? [])
    .flatMap((h) => h.containers.map((c) => ({ ...c, host: h.host })));

  const runDoctor = async () => {
    toast('Doctor run requested…');
    try {
      await post('/api/runners/homelab-doctor/run');
      toast('Homelab Doctor queued — results within a minute or two', 'ok');
    } catch (e) {
      toast(`Doctor run failed: ${(e as Error).message}`, 'crit');
    }
  };

  const syncAll = async () => {
    toast('Force Sync requested on all agents…');
    try {
      await post('/api/agents/sync-all', undefined, 30_000);
      toast('Agents synced', 'ok');
    } catch (e) {
      toast(`Sync failed: ${(e as Error).message}`, 'crit');
    }
  };

  return (
    <div className="cmdk-overlay" onClick={() => setOpen(false)}>
      <div onClick={(e) => e.stopPropagation()}>
        <Command className="cmdk glass-strong" label="Command palette">
          <Command.Input autoFocus placeholder="Go to, open, run — or ask a question…"
            value={query} onValueChange={setQuery} />
          <Command.List>
            <Command.Empty>
              {query.trim().length > 3 ? (
                <button className="tb-btn" disabled={asking} onClick={() => askHomelab(query.trim())}>
                  <BrainCircuit /> {asking ? 'Asking the local LLM…' : `Ask the homelab: “${query.trim()}”`}
                </button>
              ) : 'Nothing matches.'}
            </Command.Empty>
            <Command.Group heading="Go to">
              {GOTO.map(({ path, label, icon: Icon }) => (
                <Command.Item key={path} onSelect={() => run(() => navigate(path))}>
                  <Icon aria-hidden /> {label}
                </Command.Item>
              ))}
            </Command.Group>
            <Command.Group heading="Open">
              {OPEN.map(({ href, label, icon: Icon }) => (
                <Command.Item key={href} onSelect={() => run(() => { window.location.href = href; })}>
                  <Icon aria-hidden /> {label}
                </Command.Item>
              ))}
            </Command.Group>
            <Command.Group heading="Apps">
              {ALL_LINKS.map((l) => (
                <Command.Item key={l.label} value={`app ${l.label}`} onSelect={() => run(() => {
                  if (isExternal(l.url)) window.open(l.url, '_blank', 'noreferrer');
                  else window.location.href = l.url;
                })}>
                  <img src={iconUrl(l.icon)} alt="" width={14} height={14} />
                  {l.label}
                  <span className="hint">{l.group}</span>
                </Command.Item>
              ))}
            </Command.Group>
            {allContainers.length > 0 && (
              <Command.Group heading="Containers">
                {allContainers.map((c) => (
                  <Command.Item key={`${c.host}/${c.name}`} value={`container ${c.name} ${c.host}`}
                    onSelect={() => run(() => navigate('/containers'))}>
                    <Boxes aria-hidden /> {c.name}
                    <span className="hint">{c.host} · {c.up ? 'up' : 'down'}{c.update_available ? ' · update' : ''}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            <Command.Group heading="Actions">
              <Command.Item onSelect={() => run(() => navigate('/updates'))}>
                <ExternalLink aria-hidden /> Open the updates queue
              </Command.Item>
              <Command.Item onSelect={() => run(runDoctor)}>
                <Stethoscope aria-hidden /> Run Homelab Doctor
              </Command.Item>
              <Command.Item onSelect={() => run(syncAll)}>
                <RefreshCw aria-hidden /> Force Sync all agents
              </Command.Item>
              <Command.Item onSelect={() => run(() => { toggleTheme(); })}>
                <SunMoon aria-hidden /> Toggle theme
              </Command.Item>
            </Command.Group>
          </Command.List>
        </Command>
      </div>
    </div>
  );
}
