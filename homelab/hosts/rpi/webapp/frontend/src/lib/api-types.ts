// Shared shapes for the API payloads. Hand-written (the backend has no schema
// export); each mirrors what the corresponding route actually returns.

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
  origins: Record<string, { up: boolean; status?: number; error?: string }>;
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

// ── board engine ────────────────────────────────────────────────────────────

export interface GlassSettings { opacity: number; blur: number; dim: number }

export interface WidgetInstance {
  id: string;
  type: string;
  options?: Record<string, unknown>;
}

export interface GridItem { i: string; x: number; y: number; w: number; h: number }

export interface BoardDoc {
  slug: string;
  name: string;
  protected?: boolean;
  wallpaper: string | null;
  glass: GlassSettings | null;
  widgets: WidgetInstance[];
  layouts: Record<string, GridItem[]>;
  rev: number;
  updated_at?: string;
}

export interface BoardSummary {
  slug: string;
  name: string;
  protected: boolean;
  widgets: number;
  updated_at: string | null;
}

export interface UiSettings {
  wallpaper: string | null;
  glass: GlassSettings;
  reduce_glass: boolean;
  default_board: string;
}
