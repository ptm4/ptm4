// System widgets: host vitals, containers, storage, network, upkeep, activity,
// counters, fleet rollup. Each is a direct port of the corresponding v1 bento tile,
// reading the same endpoints — presentation, not new collection.
import { useContext, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { Power, PackagePlus, Terminal, SlidersHorizontal } from 'lucide-react';
import {
  useActivity, useContainers, useRunnerReport, useTimers, useUptime,
  useVitals, useRunners, useAgents,
  useVitalsRange, VITALS_RANGES, type VitalsRange,
} from '../lib/queries';
import { useHostActions } from '../lib/host-actions';
import { WidgetCtx } from '../board/widget-ctx';
import { durSince, fmtBytesPerSec, relTime, toneFor } from '../lib/format';
import { WidgetFrame, Vital, Sparkline, WidgetError, WidgetLoading, Pill, Meter } from './kit';

const HOST_ROLES: Record<string, string> = {
  rpi: 'DNS · DHCP · web',
  opti: 'storage · control plane',
  noblenumbat: 'media stack',
  android: 'local LLM',
};

function fmtUptime(s: number | null | undefined): string {
  if (s == null) return '—';
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  if (d > 0) return `${d}d ${h}h`;
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${m}m`;
}

// ── host-vitals ─────────────────────────────────────────────────────────────

// A metric row that highlights on hover (just the row, not the tile) and opens a
// contribution popover. Portaled to <body>: the tile clips overflow and RGL's
// transform would hijack position:fixed.
function HoverVital({
  id, active, onHover, popover, children,
}: {
  id: string;
  active: boolean;
  onHover: (id: string | null, rect?: DOMRect) => void;
  popover: ReactNode;
  children: ReactNode;
}) {
  const [rect, setRect] = useState<DOMRect | null>(null);
  return (
    <div
      className={`vital-hit${active ? ' active' : ''}`}
      onMouseEnter={(e) => { const r = e.currentTarget.getBoundingClientRect(); setRect(r); onHover(id, r); }}
      onMouseLeave={() => onHover(null)}
    >
      {children}
      {active && rect && createPortal(
        <div className="vital-pop glass-strong" style={{
          left: Math.min(rect.left, window.innerWidth - 300),
          top: rect.bottom + 8 + 260 > window.innerHeight ? undefined : rect.bottom + 8,
          bottom: rect.bottom + 8 + 260 > window.innerHeight ? window.innerHeight - rect.top + 8 : undefined,
        }}>
          {popover}
        </div>,
        document.body,
      )}
    </div>
  );
}

// Interfaces worth showing a human: the physical ones, not docker's veth forest.
const isPhysicalIface = (i: string) => !/^(veth|br-|docker0|lo$)/.test(i);

export function HostVitalsWidget({ options }: { options?: Record<string, unknown> }) {
  const host = (options?.host as string) || 'rpi';
  const optRange = (options?.range as VitalsRange) ?? '1h';
  // Clicking a graph caption cycles the range AND saves it: on a board the choice
  // is written into this widget's options (server-side, follows the board to any
  // device); rendered outside a board it falls back to localStorage.
  const ctx = useContext(WidgetCtx);
  const lsKey = `vitals-range:${host}`;
  const [localRange, setLocalRange] = useState<VitalsRange | null>(() => {
    try {
      const v = localStorage.getItem(lsKey) as VitalsRange | null;
      return v && VITALS_RANGES.includes(v) ? v : null;
    } catch { return null; }
  });
  const range: VitalsRange = ctx
    ? (VITALS_RANGES.includes(optRange) ? optRange : '1h')
    : (localRange ?? (VITALS_RANGES.includes(optRange) ? optRange : '1h'));
  const cycleRange = () => {
    const next = VITALS_RANGES[(VITALS_RANGES.indexOf(range) + 1) % VITALS_RANGES.length];
    if (ctx) {
      ctx.updateOptions({ ...(options ?? {}), range: next });
    } else {
      setLocalRange(next);
      try { localStorage.setItem(lsKey, next); } catch { /* private mode */ }
    }
  };
  const vitals = useVitals();
  const series = useVitalsRange(host, range);
  const hardware = useRunnerReport('hardware-latest');
  const doctor = useRunnerReport('homelab-doctor-latest');
  const software = useRunnerReport('software-latest');
  const agents = useAgents();
  const actions = useHostActions(host);
  const [hovered, setHovered] = useState<string | null>(null);

  const live = vitals.data?.hosts[host];
  const hw = hardware.data?.hosts?.find((h) => h.host === host);
  const doc = doctor.data?.hosts?.find((h) => h.host === host);
  const status = doc?.status || hw?.status || 'unknown';
  const metrics = (hw?.metrics ?? {}) as Record<string, any>;
  const dm = (doc?.metrics ?? {}) as Record<string, any>;
  const swm = (software.data?.hosts?.find((h) => h.host === host)?.metrics ?? {}) as Record<string, any>;
  const agent = agents.data?.hosts.find((a) => a.id === host);
  const controllable = !!agent?.reachable && Array.isArray(agent?.allowed_units);

  // ── everything the reports know about this host ───────────────────────────
  const pool = dm.pool as { used_pct: number; pool_name?: string; size_gb?: number; avail_gb?: number } | undefined;
  const disks = (metrics.disks ?? []) as { mount?: string; used_pct?: number; used_gb?: number; size_gb?: number }[];
  const smart = (metrics.smart ?? {}) as Record<string, { health?: string; reallocated?: number; pending?: number; power_on_hours?: number; temp_c?: number }>;
  const thermals = (metrics.thermals ?? []) as { sensor?: string; temp_c?: number }[];
  const containers = (dm.containers ?? []) as { name: string; status?: string }[];
  const down = containers.filter((c) => !/^up/i.test(c.status || '')).length;
  const vpn = dm.vpn as { status?: string; forwarded_port?: number; public_ip?: string } | undefined;
  const ifaces = ((metrics.interfaces ?? []) as string[]).filter(isPhysicalIface);
  const gpus = (metrics.gpus ?? []) as string[];

  const samples = series.data?.samples ?? [];
  const times = samples.map((s) => s.t);
  const cpu = live?.latest?.cpu_pct ?? null;
  const mem = live?.latest?.mem_pct ?? null;
  const temp = live?.latest?.temp_c ?? null;
  const rx = live?.latest?.rx_bps ?? null;
  const tx = live?.latest?.tx_bps ?? null;

  const memTotal = metrics.memory_gib?.MemTotal as number | undefined;
  const memUsed = metrics.mem_used_gib as number | undefined;
  const memAvail = metrics.memory_gib?.MemAvailable as number | undefined;
  const swapTotal = metrics.memory_gib?.SwapTotal as number | undefined;
  const swapUsed = metrics.swap_used_gib as number | undefined;
  const loadArr = Array.isArray(metrics.load) && metrics.load.length ? metrics.load : null;
  const cpuInfo = (metrics.cpu ?? {}) as Record<string, string>;
  const cores = parseInt(cpuInfo['CPU(s)'], 10) || null;

  const popRow = (k: string, v: ReactNode) => (
    <div className="kv-row" key={k}><span>{k}</span><span>{v}</span></div>
  );
  const sparkNote = (
    <div className="t-dim vital-pop-note">
      last {range}, {range === '1h' || range === '3h' ? '30s samples' : '5min averages'} · daily details from the hardware report
    </div>
  );

  // SMART rows are shared by every storage popover — physical drives back all mounts.
  const smartRows = Object.entries(smart).map(([dev, s]) => popRow(
    dev,
    <>
      <span className={s.health === 'PASSED' ? 't-ok' : 't-crit'}>{s.health ?? '?'}</span>
      {s.reallocated ? <span className={s.reallocated > 50 ? ' t-crit' : ' t-warn'}> · {s.reallocated} realloc</span> : null}
      {s.pending ? <span className="t-warn"> · {s.pending} pending</span> : null}
      {s.temp_c ? ` · ${s.temp_c}°C` : ''}
      {s.power_on_hours ? ` · ${Math.round(s.power_on_hours / 24 / 365 * 10) / 10}y on` : ''}
    </>,
  ));

  const cpuPop = (
    <>
      <div className="vital-pop-head">CPU — {host}</div>
      <div className="kv-rows">
        {popRow('now', cpu != null ? `${cpu.toFixed(1)}%` : '—')}
        {popRow('load 1/5/15', loadArr ? loadArr.join(' / ') : (live?.latest?.load1?.toFixed(2) ?? '—'))}
        {cores ? popRow('cores', cores) : null}
        {cpuInfo['Model name'] && popRow('model', <span className="vital-pop-clip">{cpuInfo['Model name']}</span>)}
        {gpus.length > 0 && popRow('gpu', <span className="vital-pop-clip">{gpus[0]}</span>)}
        {popRow('containers', `${containers.length - down} running${down ? `, ${down} down` : ''}`)}
      </div>
      <div className="vital-pop-spark" style={{ color: 'var(--accent)' }}>
        <Sparkline values={samples.map((s) => s.cpu_pct)} times={times} height={36}
          label="cpu history" format={(v) => `${v.toFixed(1)}%`} />
      </div>
      {sparkNote}
    </>
  );

  const memPop = (
    <>
      <div className="vital-pop-head">Memory — {host}</div>
      <div className="kv-rows">
        {popRow('now', mem != null ? `${mem.toFixed(1)}%` : '—')}
        {memUsed != null && memTotal != null && popRow('used', `${memUsed.toFixed(1)} of ${memTotal} GiB`)}
        {memAvail != null && popRow('available', `${memAvail.toFixed(1)} GiB`)}
        {swapTotal != null && swapTotal > 0 &&
          popRow('swap', `${(swapUsed ?? 0).toFixed(1)} of ${swapTotal} GiB${(swapUsed ?? 0) > swapTotal * 0.5 ? ' — heavy' : ''}`)}
        {popRow('containers', `${containers.length} sharing it`)}
      </div>
      <div className="vital-pop-spark" style={{ color: 'var(--brand)' }}>
        <Sparkline values={samples.map((s) => s.mem_pct)} times={times} height={36}
          label="memory history" format={(v) => `${v.toFixed(1)}%`} />
      </div>
      {sparkNote}
    </>
  );

  const tempPop = (
    <>
      <div className="vital-pop-head">Temperature — {host}</div>
      <div className="kv-rows">
        {temp != null && popRow('primary', `${temp.toFixed(1)}°C`)}
        {thermals.slice(0, 8).map((t, i) => popRow(t.sensor ?? `sensor ${i + 1}`,
          t.temp_c != null ? `${t.temp_c}°C` : '—'))}
        {thermals.length === 0 && popRow('sensors', 'none reported')}
      </div>
      {temp != null && (
        <div className="vital-pop-spark" style={{ color: 'var(--c-media)' }}>
          <Sparkline values={samples.map((s) => s.temp_c)} times={times} height={36}
            label="temp history" format={(v) => `${v.toFixed(1)}°C`} />
        </div>
      )}
      {sparkNote}
    </>
  );

  const netPop = (
    <>
      <div className="vital-pop-head">Network — {host}</div>
      <div className="kv-rows">
        {popRow('in', fmtBytesPerSec(rx))}
        {popRow('out', fmtBytesPerSec(tx))}
        {ifaces.length > 0 && popRow('interfaces', ifaces.join(', '))}
        {vpn?.status && popRow('vpn', `${vpn.status}${vpn.forwarded_port ? ` · port ${vpn.forwarded_port}` : ''}${vpn.public_ip ? ` · ${vpn.public_ip}` : ''}`)}
      </div>
      <div className="vital-pop-spark" style={{ color: 'var(--c-network)' }}>
        <Sparkline values={samples.map((s) => s.rx_bps)} times={times} height={36}
          label="net in history" format={(v) => `↓ ${fmtBytesPerSec(v)}`} />
      </div>
      {sparkNote}
    </>
  );

  const storagePop = (extra: ReactNode) => (
    <>
      <div className="vital-pop-head">Storage — {host}</div>
      <div className="kv-rows">{extra}</div>
      {smartRows.length > 0 && (
        <>
          <div className="vital-pop-sub">physical drives (SMART)</div>
          <div className="kv-rows">{smartRows}</div>
        </>
      )}
      <div className="t-dim vital-pop-note">daily hardware report{pool ? ' + doctor pool check' : ''}</div>
    </>
  );

  return (
    <WidgetFrame
      title={<span className="host-name">{host}</span>}
      meta={
        <span className="host-meta">
          <span className="t-dim">up {fmtUptime(live?.latest?.uptime_s) === '—' ? (metrics.uptime ?? '—') : fmtUptime(live?.latest?.uptime_s)}</span>
          <Pill tone={status === 'ok' ? 'ok' : status === 'warn' ? 'warn' : 'crit'}>{status}</Pill>
        </span>
      }
    >
      <div className="host-role">{HOST_ROLES[host] ?? ''}</div>
      {live?.error && <WidgetError message={live.error} />}
      <div className="vitals">
        <HoverVital id="cpu" active={hovered === 'cpu'} onHover={setHovered} popover={cpuPop}>
          <Vital label="CPU" value={cpu != null ? `${Math.round(cpu)}%` : '—'}
            sub={loadArr ? ` load ${loadArr[0]}` : live?.latest?.load1 != null ? ` load ${live.latest.load1.toFixed(2)}` : undefined}
            pct={cpu} />
        </HoverVital>
        <HoverVital id="mem" active={hovered === 'mem'} onHover={setHovered} popover={memPop}>
          <Vital label="Memory" value={mem != null ? `${Math.round(mem)}%` : '—'}
            sub={memTotal ? ` of ${memTotal} GiB` : undefined} pct={mem} />
        </HoverVital>
        <HoverVital id="temp" active={hovered === 'temp'} onHover={setHovered} popover={tempPop}>
          <Vital label="Temp" value={temp != null ? `${Math.round(temp)}°C` : '—'}
            sub={thermals.length > 1 ? ` ${thermals.length} sensors` : undefined} />
        </HoverVital>
        <HoverVital id="net" active={hovered === 'net'} onHover={setHovered} popover={netPop}>
          <Vital label="Network"
            value={<span className="net-pair">↓{fmtBytesPerSec(rx).replace(' ', ' ')} ↑{fmtBytesPerSec(tx).replace(' ', ' ')}</span>}
            sub={vpn?.status ? ` vpn ${vpn.status}` : undefined} />
        </HoverVital>
      </div>

      {/* every drive, partition and pool this host has — not just the first */}
      {(pool || disks.length > 0) && (
        <div className="disk-rows">
          {pool && (
            <HoverVital id="pool" active={hovered === 'pool'} onHover={setHovered}
              popover={storagePop(<>
                {popRow(`pool ${pool.pool_name ?? ''}`, `${pool.used_pct}% of ${Math.round(pool.size_gb ?? 0)} GB`)}
                {pool.avail_gb != null && popRow('free', `${Math.round(pool.avail_gb)} GB`)}
              </>)}>
              <div className="disk-row">
                <span className="disk-label mono">{pool.pool_name ?? 'pool'} <small>zfs</small></span>
                <Meter pct={pool.used_pct} />
                <span className="disk-val">{Math.round(pool.used_pct)}%<small> of {Math.round((pool.size_gb ?? 0) / 100) / 10} TB</small></span>
              </div>
            </HoverVital>
          )}
          {disks.map((d, i) => (
            <HoverVital key={d.mount ?? i} id={`disk-${i}`} active={hovered === `disk-${i}`} onHover={setHovered}
              popover={storagePop(<>
                {popRow(d.mount ?? `disk ${i + 1}`,
                  `${d.used_pct ?? '—'}%${d.used_gb != null && d.size_gb != null ? ` · ${Math.round(d.used_gb)} of ${Math.round(d.size_gb)} GB` : ''}`)}
                {d.size_gb != null && d.used_gb != null && popRow('free', `${Math.round(d.size_gb - d.used_gb)} GB`)}
              </>)}>
              <div className="disk-row">
                <span className="disk-label mono">{d.mount ?? `disk ${i + 1}`}</span>
                <Meter pct={d.used_pct ?? null} />
                <span className="disk-val">{d.used_pct ?? '—'}%<small>{d.size_gb ? ` of ${Math.round(d.size_gb)} GB` : ''}</small></span>
              </div>
            </HoverVital>
          ))}
        </div>
      )}
      {samples.length > 1 && (
        <div className="sparks">
          <span className="spark-wrap" style={{ color: 'var(--c-network)' }}>
            <button className="spark-cap spark-cap-btn" onClick={cycleRange}
              title="Click to cycle the range">CPU % · {range}</button>
            <Sparkline values={samples.map((s) => s.cpu_pct)} times={times}
              showDay={range === '24h' || range === '48h'}
              label={`${host} CPU`} format={(v) => `cpu ${v.toFixed(1)}%`} />
          </span>
          <span className="spark-wrap" style={{ color: 'var(--brand)' }}>
            <button className="spark-cap spark-cap-btn" onClick={cycleRange}
              title="Click to cycle the range">MEM % · {range}</button>
            <Sparkline values={samples.map((s) => s.mem_pct)} times={times}
              showDay={range === '24h' || range === '48h'}
              label={`${host} memory`} format={(v) => `mem ${v.toFixed(1)}%`} />
          </span>
        </div>
      )}
      <div className="w-foot">
        {containers.length > 0 && (
          <>
            <span>{containers.length - down}/{containers.length} containers</span>
            <span className="cstrip">
              {containers.map((c) => (
                <span key={c.name} className="cdot"
                  data-s={/^up/i.test(c.status || '') ? 'ok' : 'crit'}
                  title={`${c.name} — ${c.status || 'unknown'}`} />
              ))}
            </span>
            {down > 0 && <span className="t-crit">{down} down</span>}
          </>
        )}
        {swm.pending_count ? (
          <span className="chip" title={swm.reboot_pkgs ?? ''}>
            {swm.pending_count} pkg{swm.security_count ? <b className="t-crit"> · {swm.security_count} sec</b> : null}
          </span>
        ) : null}
        {swm.reboot_required && <span className="chip" data-s="warn">reboot req</span>}
        {swm.image_update_count ? <span className="chip">{swm.image_update_count} image{swm.image_update_count > 1 ? 's' : ''}</span> : null}
      </div>
      <div className="w-actions host-actions">
        {controllable ? (
          <>
            <button className="tb-btn sm danger" disabled={actions.busy} onClick={actions.reboot}
              title={`Reboot ${host} (typed confirm)`}><Power /> Reboot</button>
            <button className="tb-btn sm" disabled={actions.busy} onClick={actions.aptUpgrade}
              title={`Run homelab-autoupdate on ${host} now`}><PackagePlus /> Apt</button>
          </>
        ) : (
          <span className="t-dim host-actions-note">
            {agent?.reachable === false ? 'agent unreachable' : 'controls need agent v0.4.0'}
          </span>
        )}
        <a className="tb-btn sm" href={actions.termUrl} target="_blank" rel="noreferrer"
          title={`Terminal on ${host} via Cockpit (rpi:9090, system login)`}><Terminal /> Term</a>
        <Link className="tb-btn sm" to="/cockpit" title="All host controls"><SlidersHorizontal /> More</Link>
      </div>
      {actions.dialog}
    </WidgetFrame>
  );
}

// ── containers ──────────────────────────────────────────────────────────────
export function ContainersWidget({ options }: { options?: Record<string, unknown> }) {
  const q = useContainers();
  const compact = options?.compact === true;
  if (q.isLoading) return <WidgetFrame title="Containers"><WidgetLoading /></WidgetFrame>;
  if (q.isError) return <WidgetFrame title="Containers"><WidgetError message="containers unavailable" /></WidgetFrame>;

  const hosts = q.data?.hosts ?? [];
  const total = hosts.reduce((n, h) => n + h.containers.length, 0);
  const up = hosts.reduce((n, h) => n + h.containers.filter((c) => c.up).length, 0);

  if (compact) {
    const updates = hosts.reduce((n, h) => n + h.containers.filter((c) => c.update_available).length, 0);
    return (
      <WidgetFrame title="Containers" meta={<Link to="/containers">open →</Link>}>
        <div className="big-metric" data-s={up === total ? 'ok' : 'crit'}>{up}/{total}<small> up</small></div>
        <div className="kv-rows">
          {hosts.filter((h) => h.containers.length > 0).map((h) => {
            const downList = h.containers.filter((c) => !c.up).map((c) => c.name);
            return (
              <div className="kv-row" key={h.host}>
                <span>{h.host}</span>
                <span>
                  {h.containers.length - downList.length}/{h.containers.length}
                  {downList.length > 0 && <span className="t-crit"> · down: {downList.join(', ')}</span>}
                </span>
              </div>
            );
          })}
        </div>
        <div className="w-foot">
          <span className="cstrip">
            {hosts.flatMap((h) => h.containers.map((c) => (
              <span key={`${h.host}/${c.name}`} className="cdot" data-s={c.up ? 'ok' : 'crit'}
                title={`${c.name} (${h.host})`} />
            )))}
          </span>
          {updates > 0 && <span className="chip">{updates} update{updates > 1 ? 's' : ''}</span>}
        </div>
      </WidgetFrame>
    );
  }

  return (
    <WidgetFrame title="Containers" meta={<Link to="/containers">{up}/{total} up · open →</Link>} scroll>
      <table className="ctable">
        <tbody>
          {hosts.flatMap((h) => h.containers.map((c) => (
            <tr key={`${h.host}/${c.name}`}>
              <td><span className="cdot" data-s={c.up ? 'ok' : 'crit'} /></td>
              <td className="mono">{c.name}</td>
              <td className="t-dim">{h.host}</td>
              <td className="t-dim">{c.status_since ? durSince(c.status_since) : (c.status ?? '')}</td>
              <td>{c.update_available && <span className="badge badge-stale">update</span>}</td>
            </tr>
          )))}
        </tbody>
      </table>
    </WidgetFrame>
  );
}

// ── activity ────────────────────────────────────────────────────────────────
export function ActivityWidget({ options }: { options?: Record<string, unknown> }) {
  const limit = (options?.limit as number) ?? 20;
  const q = useActivity(limit);
  if (q.isLoading) return <WidgetFrame title="Activity"><WidgetLoading /></WidgetFrame>;
  if (q.isError) return <WidgetFrame title="Activity"><WidgetError message="activity unavailable" /></WidgetFrame>;

  return (
    <WidgetFrame title="Activity" meta="from latest reports" scroll>
      <ul className="feed">
        {(q.data?.events ?? []).map((e, i) => (
          <li key={i} data-sev={e.severity}>
            <span className="feed-dot" />
            <span className="feed-msg">{e.message}</span>
            <span className="feed-meta">{e.host ? `${e.host} · ` : ''}{e.source} · {relTime(e.ts)}</span>
          </li>
        ))}
        {q.data?.events.length === 0 && <li className="t-dim">Nothing reported.</li>}
      </ul>
    </WidgetFrame>
  );
}

// ── storage ─────────────────────────────────────────────────────────────────
export function StorageWidget() {
  const doctor = useRunnerReport('homelab-doctor-latest');
  const hardware = useRunnerReport('hardware-latest');
  const opti = doctor.data?.hosts?.find((h) => h.host === 'opti');
  const pool = (opti?.metrics as any)?.pool as { used_pct?: number; size_gb?: number; free_gb?: number; pool_name?: string } | undefined;

  return (
    <WidgetFrame title="Storage & disks" meta={<Pill>opti</Pill>}>
      {pool ? (
        <>
          <div className="big-metric">{Math.round(pool.used_pct ?? 0)}%<small> {pool.pool_name ?? 'pool'}</small></div>
          <Meter pct={pool.used_pct ?? null} />
          <div className="t-dim">
            {pool.free_gb != null ? `${Math.round(pool.free_gb)} GB free` : ''}
            {pool.size_gb != null ? ` of ${Math.round(pool.size_gb)} GB` : ''}
          </div>
        </>
      ) : <WidgetError message="no pool data in the latest doctor report" />}
      <div className="kv-rows">
        {(hardware.data?.hosts ?? []).map((h) => {
          const d = ((h.metrics as any)?.disks ?? [])[0];
          if (!d) return null;
          return (
            <div className="kv-row" key={h.host}>
              <span>{h.host}</span>
              <span className={`t-${toneFor(d.used_pct) || 'dim'}`}>{d.used_pct}%{d.size_gb ? ` of ${Math.round(d.size_gb)} GB` : ''}</span>
            </div>
          );
        })}
      </div>
    </WidgetFrame>
  );
}

// ── network ─────────────────────────────────────────────────────────────────
export function NetworkWidget() {
  const q = useRunnerReport('network-latest');
  const hosts = q.data?.hosts ?? [];
  return (
    <WidgetFrame title="Network" meta={q.data?.run_at ? relTime(q.data.run_at) : undefined}>
      {q.isLoading && <WidgetLoading />}
      <div className="kv-rows">
        {hosts.map((h) => {
          const m = (h.metrics ?? {}) as Record<string, any>;
          const detail = m.ping_ms != null ? `${m.ping_ms} ms`
            : m.reachable === false ? 'unreachable'
            : (h.summary ?? '');
          return (
            <div className="kv-row" key={h.host}>
              <span>{h.host}</span>
              <span className={h.status === 'ok' ? '' : 't-warn'}>{detail}</span>
            </div>
          );
        })}
        {hosts.length === 0 && !q.isLoading && <div className="t-dim">No network report yet.</div>}
      </div>
    </WidgetFrame>
  );
}

// ── upkeep (systemd timers) ─────────────────────────────────────────────────
export function UpkeepWidget() {
  const q = useTimers();
  const rows = (q.data?.hosts ?? []).flatMap((h) => h.timers.map((t) => ({ ...t, host: h.host })));
  return (
    <WidgetFrame title="Services & upkeep" meta={`${rows.length} timers`} scroll>
      {q.isLoading && <WidgetLoading />}
      <div className="kv-rows">
        {rows.map((t) => (
          <div className="kv-row" key={`${t.host}/${t.unit}`}>
            <span className="mono">{t.unit.replace(/\.timer$/, '')}</span>
            <span className="t-dim">{t.host} · {t.passed ?? '—'}</span>
          </div>
        ))}
        {rows.length === 0 && !q.isLoading && <div className="t-dim">No timers reported.</div>}
      </div>
    </WidgetFrame>
  );
}

// ── fleet-status (the v1 ribbon, as a widget) ───────────────────────────────
export function FleetStatusWidget() {
  const runners = useRunners();
  const agents = useAgents();
  const uptime = useUptime();

  // Only runners that have actually reported drive the fleet pill: a manual or
  // never-run runner sits at "unknown" forever, and treating that as critical
  // painted a red warning over a healthy fleet in v1.
  const reporting = (runners.data?.runners ?? []).filter((r) => r.run_at && r.status && r.status !== 'unknown');
  const rank: Record<string, number> = { critical: 0, warn: 1, ok: 2 };
  const worst = reporting.reduce((w, r) => ((rank[r.status] ?? 1) < (rank[w] ?? 2) ? r.status : w), 'ok');
  const reach = (agents.data?.hosts ?? []).filter((h) => h.reachable).length;
  const ku = uptime.data;

  return (
    <WidgetFrame title="Fleet">
      <div className="fleet-row">
        <Pill tone={worst === 'ok' ? 'ok' : worst === 'warn' ? 'warn' : 'crit'}>
          {worst === 'ok' ? '✓ fleet ok' : `! ${worst}`}
        </Pill>
        {ku?.ok && (
          <Pill tone={ku.down ? 'crit' : ku.pending ? 'warn' : 'ok'}>{ku.up}/{ku.total} monitors</Pill>
        )}
        <Pill>{reach}/{agents.data?.hosts.length ?? 3} agents</Pill>
      </div>
      <div className="fleet-fresh">
        {reporting.map((r) => `${r.label.split(' ')[0].toLowerCase()} ${relTime(r.run_at)}`).join(' · ')}
      </div>
    </WidgetFrame>
  );
}

// ── monitors (Uptime Kuma) ──────────────────────────────────────────────────
export function MonitorsWidget() {
  const q = useUptime();
  if (q.isError || q.data?.ok === false) {
    return <WidgetFrame title="Monitors"><WidgetError message="Uptime Kuma unavailable" /></WidgetFrame>;
  }
  return (
    <WidgetFrame title="Monitors" meta={q.data ? `${q.data.up}/${q.data.total} up` : undefined} scroll>
      {q.isLoading && <WidgetLoading />}
      <div className="mon-grid">
        {(q.data?.monitors ?? []).map((m) => (
          <span className="mon" key={m.name} title={m.ms != null ? `${m.ms} ms` : m.status}>
            <span className="cdot" data-s={m.status === 'up' ? 'ok' : m.status === 'down' ? 'crit' : 'warn'} />
            {m.name}
          </span>
        ))}
      </div>
    </WidgetFrame>
  );
}

// ── stat counters ───────────────────────────────────────────────────────────
const STAT_DEFS: Record<string, { label: string; sub: string; to: string }> = {
  monitors: { label: 'Monitors', sub: 'Uptime Kuma', to: '/cockpit' },
  reports: { label: 'Reports', sub: 'runner status', to: '/reports' },
  drift: { label: 'Agent drift', sub: 'undescribed vs missing', to: '/agents/' },
  updates: { label: 'Updates', sub: 'container images', to: '/updates' },
};

export function StatWidget({ options }: { options?: Record<string, unknown> }) {
  const metric = (options?.metric as string) || 'monitors';
  const def = STAT_DEFS[metric] ?? STAT_DEFS.monitors;

  const uptime = useUptime();
  const runners = useRunners();
  const agents = useAgents();
  const containers = useContainers();

  let value = '—';
  let tone: string | undefined;
  let sub = def.sub;

  if (metric === 'monitors' && uptime.data?.ok) {
    value = `${uptime.data.up}/${uptime.data.total}`;
    tone = uptime.data.down ? 'crit' : 'ok';
    const bad = uptime.data.monitors.filter((m) => m.status !== 'up').map((m) => m.name);
    sub = bad.length ? `down: ${bad.join(', ')}` : 'all up';
  } else if (metric === 'reports' && runners.data) {
    const bad = runners.data.runners.filter((r) => r.status === 'critical' || r.status === 'warn').length;
    value = `${runners.data.runners.length - bad}/${runners.data.runners.length}`;
    tone = bad ? 'warn' : 'ok';
    sub = bad ? `${bad} need attention` : 'all healthy';
  } else if (metric === 'drift' && agents.data) {
    const n = agents.data.hosts.reduce((acc, h) => acc + (h.drift_count || 0), 0);
    value = String(n);
    tone = n ? 'warn' : 'ok';
  } else if (metric === 'updates' && containers.data) {
    const n = containers.data.hosts.reduce(
      (acc, h) => acc + h.containers.filter((c) => c.update_available).length, 0);
    value = String(n);
    tone = n ? 'warn' : 'ok';
    sub = n ? 'images out of date' : 'all current';
  }

  const inner = (
    <>
      <div className="w-title">{def.label}</div>
      <div className="big-metric" data-s={tone}>{value}</div>
      <div className="t-dim stat-sub">{sub}</div>
    </>
  );

  return def.to.startsWith('/') && !def.to.includes('.')
    ? <Link className="w-card glass w-link stat" to={def.to}>{inner}</Link>
    : <a className="w-card glass w-link stat" href={def.to}>{inner}</a>;
}
