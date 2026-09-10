// Shared shapes for the API payloads. Hand-written (the backend has no schema
// export); each mirrors what the corresponding route actually returns. Response shapes
// are frozen by the deploy smoke gate, so these are safe to rely on.

export interface VitalsSample {
  t: number;
  load1: number | null;
  cpu_pct: number | null;
  mem_pct: number | null;
  temp_c: number | null;
  rx_bps: number | null;
  tx_bps: number | null;
  uptime_s: number | null;
}

export interface VitalsRollup {
  hosts: Record<string, {
    count: number;
    latest: VitalsSample | null;
    agent_version: string | null;
    error: string | null;
  }>;
  interval_s: number;
}

export interface VitalsSeries {
  host: string;
  cores: unknown;
  error: string | null;
  samples: VitalsSample[];
  latest: VitalsSample | null;
}

export interface MonitorProcess {
  pid: number; identity: string; program: string; command: string; user: string; state: string;
  ppid: number; threads: number; start_ticks: number; memory_bytes: number; cpu_pct: number | null;
  read_bps: number | null; write_bps: number | null;
}

export interface MonitorSample {
  measured_at: string; boot_id: string; uptime_s?: number | null; cpu: { total_pct: number | null; core_pct: Record<string, number | null>; load: (number | null)[] };
  memory: { total_bytes: number | null; available_bytes: number | null; used_bytes: number | null; swap_total_bytes: number | null; swap_free_bytes: number | null };
  network: Record<string, { rx_bps: number | null; tx_bps: number | null; rx_errors: number; tx_errors: number; rx_drops: number; tx_drops: number }>;
  disks: Record<string, { read_bps: number | null; write_bps: number | null; read_iops: number | null; write_iops: number | null; busy_pct: number | null }>;
  mounts: { mount: string; source: string; fs_type: string; total_bytes: number; available_bytes: number }[];
  temperatures: { label: string; celsius: number }[];
  power: { name: string; watts: number | null }[];
  battery: { name: string; status: string | null; capacity_pct: number | null; power_uw: number | null }[];
  gpu: { id: string; driver: string; clock_current_mhz: number | null; clock_active_mhz: number | null; busy_pct: number | null; utilization_status: string; memory_kind: string | null }[];
  processes: MonitorProcess[];
}

export interface MonitorRollup {
  interval_s: number; generated_at: string;
  hosts: Record<string, { latest: MonitorSample | null; count: number; error: string | null; measured_at: string | null; capabilities: unknown }>;
}

export interface ContainerRow {
  name: string;
  status: string | null;
  state?: string | null;
  status_since?: string | null;
  image?: string | null;
  compose_project?: string | null;
  ports?: { container_port?: string; host_port?: string; host_ip?: string; proto?: string }[];
  up: boolean;
  update_available: boolean;
}

export interface ContainersResp {
  hosts: { host: string; doctor_at: string | null; fragment_at: string | null; containers: ContainerRow[] }[];
}

export interface ActivityEvent {
  ts: string | null;
  source: string;
  severity: string;
  host: string | null;
  message: string;
}

export interface ActivityResp { events: ActivityEvent[] }

export interface TimersResp {
  hosts: { host: string; timers: { unit: string; next: string | null; passed: string | null }[] }[];
}

export interface PiholeSummary {
  dns_queries_today: number | null;
  ads_blocked_today: number | null;
  ads_percentage_today: number | null;
  unique_clients: number | null;
  gravity_domains: number | null;
  blocking: { enabled: boolean; timer: number | null } | null;
}

export interface UptimeResp {
  ok: boolean;
  total: number;
  up: number;
  down: number;
  pending: number;
  monitors: { name: string; status: string; ms: number | null }[];
}

export interface AgentRow {
  id: string;
  label: string;
  reachable: boolean;
  error?: string;
  last_run: string | null;
  agent_version: string | null;
  drift_count: number;
  allowed_units?: string[] | null;
  wake_targets?: string[];
}

export interface AgentsResp { hosts: AgentRow[] }

export interface RunnerRow {
  name: string;
  label: string;
  agent: string | null;
  status: string;
  summary: string;
  run_at: string | null;
  stale: boolean;
  has_alert?: boolean;
  enabled: boolean;
}

export interface RunnersResp { runners: RunnerRow[] }

export interface LinkcheckResp {
  /** `up: null` means this tier cannot reach the origin at all (firewall, network
   *  segment) — explicitly NOT the same as down. `note` says why. */
  origins: Record<string, { up: boolean | null; status?: number; error?: string; note?: string }>;
}

export interface HostReport {
  status?: string;
  run_at?: string;
  hosts?: {
    host: string;
    status?: string;
    summary?: string;
    metrics?: Record<string, unknown>;
  }[];
}

export interface Notification {
  id: string;
  source: string;
  severity: string;
  host: string | null;
  message: string;
  ts: string | null;
  acked: boolean;
}

export interface NotificationsResp { items: Notification[]; unacked: number; total: number }

export interface UpdatesResp {
  images?: { host: string; name: string; image?: string; current?: string | null; latest?: string | null }[];
  apt?: { host: string; count: number; security?: number; packages?: string[] }[];
  [k: string]: unknown;
}

// ── appearance ──────────────────────────────────────────────────────────────

export interface GlassSettings { opacity: number; blur: number; dim: number }

export interface UiSettings {
  wallpaper: string | null;
  glass: GlassSettings;
  reduce_glass: boolean;
  default_board: string;
  /** v3: Launchpad favourites (service ids) */
  favorites?: string[];
}
