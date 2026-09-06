//! Data model: the sampler's [`Snapshot`], the [`ViewModel`] the painter draws, formatting
//! rules ported from the legacy `app.js`, sparkline rings, thresholds and dirty tracking.
//! Pure code — no Win32 — so it is unit-tested.

use crate::theme::{self, Palette};

// ── Snapshot (what the sampler produces) ──────────────────────────────────────

#[derive(Clone, Debug, PartialEq, Default)]
pub struct DiskStat {
    /// "C:"
    pub letter: String,
    /// Volume label ("Windows"), may be empty.
    pub label: String,
    pub used_bytes: u64,
    pub total_bytes: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Default)]
pub enum GpuSource {
    #[default]
    None,
    Nvml,
    Pdh,
}

#[derive(Clone, Debug, PartialEq, Default)]
pub struct GpuStat {
    pub source: GpuSource,
    pub util_pct: Option<f32>,
    pub vram_used: Option<u64>,
    pub vram_total: Option<u64>,
    pub temp_c: Option<u32>,
    pub power_w: Option<f32>,
}

#[derive(Clone, Debug, PartialEq, Default)]
pub struct Snapshot {
    pub seq: u64,
    /// False when a core sampler failed this tick (status dot turns red).
    pub ok: bool,
    /// None until the second CPU sample exists (or after a re-baseline).
    pub cpu_pct: Option<f32>,
    pub ram_used: u64,
    pub ram_total: u64,
    pub gpu: GpuStat,
    pub disks: Vec<DiskStat>,
    /// Bytes per second; None when the baseline is invalid (first tick, resume).
    pub net_rx_bps: Option<f64>,
    pub net_tx_bps: Option<f64>,
    /// Link speed of the selected adapter in bits/s, if known.
    pub net_link_bps: Option<u64>,
    pub uptime_s: u64,
}

// ── Formatting (legacy app.js rules, tidied) ──────────────────────────────────

const GIB: f64 = 1_073_741_824.0;

pub fn fmt_pct(v: f32) -> String {
    format!("{}%", v.clamp(0.0, 100.0).round() as u32)
}

/// "8.2 / 16 GB"
pub fn fmt_ram(used: u64, total: u64) -> String {
    format!("{:.1} / {} GB", used as f64 / GIB, (total as f64 / GIB).round() as u64)
}

/// "567 / 931 GB" (whole GB) — or TB above 1000 GB.
pub fn fmt_disk(used: u64, total: u64) -> String {
    let (u, t) = (used as f64 / GIB, total as f64 / GIB);
    if t >= 1000.0 {
        format!("{:.2} / {:.2} TB", u / 1024.0, t / 1024.0)
    } else {
        format!("{} / {} GB", u.round() as u64, t.round() as u64)
    }
}

/// "1.2 / 12 GB" for VRAM (MiB-based values from NVML).
pub fn fmt_vram(used: u64, total: u64) -> String {
    fmt_ram(used, total)
}

/// Bits per second, adaptive: "0 bps" / "312 Kbps" / "1.24 Mbps" / "1.02 Gbps".
pub fn fmt_bits(bps: f64) -> String {
    let b = bps * 8.0;
    if b < 1_000.0 {
        "0 Kbps".to_string()
    } else if b < 1_000_000.0 {
        format!("{} Kbps", (b / 1_000.0).round() as u64)
    } else if b < 1_000_000_000.0 {
        format!("{:.2} Mbps", b / 1_000_000.0)
    } else {
        format!("{:.2} Gbps", b / 1_000_000_000.0)
    }
}

/// Bytes per second: "156 KB/s" / "12.4 MB/s".
pub fn fmt_bytes_rate(bps: f64) -> String {
    if bps >= 1_048_576.0 {
        format!("{:.1} MB/s", bps / 1_048_576.0)
    } else {
        format!("{} KB/s", (bps / 1024.0).round() as u64)
    }
}

/// "UP 1D 03H 22M" / "UP 03H 22M" / "UP 22M"
pub fn fmt_uptime(secs: u64) -> String {
    let d = secs / 86_400;
    let h = (secs % 86_400) / 3_600;
    let m = (secs % 3_600) / 60;
    if d > 0 {
        format!("UP {d}D {h:02}H {m:02}M")
    } else if h > 0 {
        format!("UP {h:02}H {m:02}M")
    } else {
        format!("UP {m}M")
    }
}

// ── Sparkline ring ────────────────────────────────────────────────────────────

#[derive(Clone, Debug, PartialEq)]
pub struct Ring {
    buf: Vec<f32>,
    head: usize,
    len: usize,
}

impl Ring {
    pub fn new(capacity: usize) -> Self {
        Ring { buf: vec![0.0; capacity.max(2)], head: 0, len: 0 }
    }
    pub fn capacity(&self) -> usize {
        self.buf.len()
    }
    pub fn len(&self) -> usize {
        self.len
    }
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
    pub fn push(&mut self, v: f32) {
        self.buf[self.head] = v;
        self.head = (self.head + 1) % self.buf.len();
        self.len = (self.len + 1).min(self.buf.len());
    }
    /// Oldest → newest.
    pub fn iter(&self) -> impl Iterator<Item = f32> + '_ {
        let cap = self.buf.len();
        let start = (self.head + cap - self.len) % cap;
        (0..self.len).map(move |i| self.buf[(start + i) % cap])
    }
    pub fn max(&self) -> f32 {
        self.iter().fold(0.0, f32::max)
    }
    /// Re-size keeping the newest samples (used when `interval_ms` changes).
    pub fn resize(&mut self, capacity: usize) {
        let items: Vec<f32> = self.iter().collect();
        let mut r = Ring::new(capacity);
        for v in items.iter().rev().take(capacity).rev() {
            r.push(*v);
        }
        *self = r;
    }
}

// ── View model ────────────────────────────────────────────────────────────────

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Level {
    Normal,
    Warn,
    Crit,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Spark {
    Cpu,
    Gpu,
    Rx,
    Tx,
}

#[derive(Clone, Debug, PartialEq)]
pub struct RowModel {
    pub label: String,
    /// 0..1 bar fill.
    pub frac: f32,
    pub value: String,
    pub sub: Option<String>,
    pub palette: Palette,
    pub level: Level,
    pub spark: Option<Spark>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Section {
    pub name: &'static str,
    pub rows: Vec<RowModel>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ViewModel {
    pub title: String,
    pub sections: Vec<Section>,
    pub footer_left: String,
    pub footer_right: String,
    pub status_ok: bool,
    pub sparklines: bool,
    pub ring_cpu: Ring,
    pub ring_gpu: Ring,
    pub ring_rx: Ring,
    pub ring_tx: Ring,
    last_rendered: Option<Box<ViewModel>>,
}

/// Window width in DIPs is fixed; height depends on content.
impl ViewModel {
    pub fn new(sparklines: bool, ring_capacity: usize) -> Self {
        ViewModel {
            title: "PTMONITOR".into(),
            sections: Vec::new(),
            footer_left: "—".into(),
            footer_right: String::new(),
            status_ok: true,
            sparklines,
            ring_cpu: Ring::new(ring_capacity),
            ring_gpu: Ring::new(ring_capacity),
            ring_rx: Ring::new(ring_capacity),
            ring_tx: Ring::new(ring_capacity),
            last_rendered: None,
        }
    }

    pub fn ring(&self, s: Spark) -> &Ring {
        match s {
            Spark::Cpu => &self.ring_cpu,
            Spark::Gpu => &self.ring_gpu,
            Spark::Rx => &self.ring_rx,
            Spark::Tx => &self.ring_tx,
        }
    }

    pub fn set_ring_capacity(&mut self, capacity: usize) {
        for r in [&mut self.ring_cpu, &mut self.ring_gpu, &mut self.ring_rx, &mut self.ring_tx] {
            if r.capacity() != capacity {
                r.resize(capacity);
            }
        }
    }

    /// Height of a row (sparkline rows are taller).
    pub fn row_height(&self, row: &RowModel) -> f32 {
        if self.sparklines && row.spark.is_some() {
            theme::ROW_H + theme::SPARK_EXTRA
        } else {
            theme::ROW_H
        }
    }

    /// Total card height in DIPs.
    pub fn content_height(&self) -> f32 {
        let mut h = theme::HEADER_H + theme::STATS_PAD;
        for (i, sec) in self.sections.iter().enumerate() {
            if i > 0 {
                h += theme::GROUP_GAP;
            }
            h += theme::BAND_H;
            for (j, row) in sec.rows.iter().enumerate() {
                if j > 0 {
                    h += theme::ROW_GAP;
                }
                h += self.row_height(row);
            }
        }
        h + theme::STATS_PAD + theme::FOOTER_H
    }

    /// Fold a snapshot into the view. Rates that are `None` keep the previously shown
    /// text so a resume never flashes to zero. Returns true when something visible changed.
    pub fn ingest(&mut self, s: &Snapshot) -> bool {
        let prev: Vec<RowModel> = self.sections.iter().flat_map(|s| s.rows.iter().cloned()).collect();
        let prev_row = |label: &str| prev.iter().find(|r| r.label == label).cloned();
        let carry = |label: &str, palette: Palette, spark: Option<Spark>| {
            prev_row(label).unwrap_or(RowModel {
                label: label.to_string(),
                frac: 0.0,
                value: "—".into(),
                sub: None,
                palette,
                level: Level::Normal,
                spark,
            })
        };

        // SYSTEM
        let cpu = match s.cpu_pct {
            Some(v) => {
                self.ring_cpu.push(v);
                RowModel {
                    label: "CPU".into(),
                    frac: v / 100.0,
                    value: fmt_pct(v),
                    sub: None,
                    palette: Palette::Cpu,
                    level: level_pct(v, 90.0, 98.0),
                    spark: Some(Spark::Cpu),
                }
            }
            None => carry("CPU", Palette::Cpu, Some(Spark::Cpu)),
        };
        let ram_pct = if s.ram_total > 0 { s.ram_used as f32 / s.ram_total as f32 * 100.0 } else { 0.0 };
        let ram = RowModel {
            label: "RAM".into(),
            frac: ram_pct / 100.0,
            value: fmt_pct(ram_pct),
            sub: Some(fmt_ram(s.ram_used, s.ram_total)),
            palette: Palette::Ram,
            level: level_pct(ram_pct, 85.0, 95.0),
            spark: None,
        };
        let gpu = match s.gpu.util_pct {
            Some(v) => {
                self.ring_gpu.push(v);
                RowModel {
                    label: "GPU".into(),
                    frac: v / 100.0,
                    value: fmt_pct(v),
                    sub: match (s.gpu.vram_used, s.gpu.vram_total) {
                        (Some(u), Some(t)) if t > 0 => Some(fmt_vram(u, t)),
                        _ => None,
                    },
                    palette: Palette::Gpu,
                    level: Level::Normal,
                    spark: Some(Spark::Gpu),
                }
            }
            None => {
                let mut r = carry("GPU", Palette::Gpu, Some(Spark::Gpu));
                if s.gpu.source == GpuSource::None {
                    r.value = "—".into();
                    r.sub = None;
                    r.frac = 0.0;
                }
                r
            }
        };

        // STORAGE
        let disks: Vec<RowModel> = s
            .disks
            .iter()
            .map(|d| {
                let pct = if d.total_bytes > 0 { d.used_bytes as f32 / d.total_bytes as f32 * 100.0 } else { 0.0 };
                RowModel {
                    label: d.letter.clone(),
                    frac: pct / 100.0,
                    value: fmt_pct(pct),
                    sub: Some(fmt_disk(d.used_bytes, d.total_bytes)),
                    palette: Palette::Disk,
                    level: level_pct(pct, 90.0, 97.0),
                    spark: None,
                }
            })
            .collect();

        // NETWORK — bar scale: link speed if known, else 1 Gbps.
        let full = s.net_link_bps.unwrap_or(1_000_000_000) as f64 / 8.0;
        let net_row = |label: &str, bps: Option<f64>, palette: Palette, spark: Spark, ring: &mut Ring| match bps {
            Some(b) => {
                ring.push(b as f32);
                RowModel {
                    label: label.into(),
                    frac: (b / full.max(1.0)) as f32,
                    value: fmt_bits(b),
                    sub: Some(fmt_bytes_rate(b)),
                    palette,
                    level: Level::Normal,
                    spark: Some(spark),
                }
            }
            None => carry(label, palette, Some(spark)),
        };
        let rx = net_row("DOWN", s.net_rx_bps, Palette::NetDown, Spark::Rx, &mut self.ring_rx);
        let tx = net_row("UP", s.net_tx_bps, Palette::NetUp, Spark::Tx, &mut self.ring_tx);

        self.sections = vec![
            Section { name: "SYSTEM", rows: vec![cpu, ram, gpu] },
            Section { name: "STORAGE", rows: disks },
            Section { name: "NETWORK", rows: vec![rx, tx] },
        ];
        self.sections.retain(|sec| !sec.rows.is_empty());
        self.footer_left = fmt_uptime(s.uptime_s);
        self.footer_right = match (s.gpu.temp_c, s.gpu.power_w) {
            (Some(t), Some(p)) => format!("{t}°  {}W", p.round() as u32),
            (Some(t), None) => format!("{t}°"),
            (None, Some(p)) => format!("{}W", p.round() as u32),
            (None, None) => String::new(),
        };
        self.status_ok = s.ok;
        self.take_dirty()
    }

    /// True when the visible content differs from what was last marked rendered.
    fn take_dirty(&mut self) -> bool {
        let same = match &self.last_rendered {
            Some(prev) => {
                prev.sections == self.sections
                    && prev.footer_left == self.footer_left
                    && prev.footer_right == self.footer_right
                    && prev.status_ok == self.status_ok
                    && prev.sparklines == self.sparklines
                    && (!self.sparklines
                        || (prev.ring_cpu == self.ring_cpu
                            && prev.ring_gpu == self.ring_gpu
                            && prev.ring_rx == self.ring_rx
                            && prev.ring_tx == self.ring_tx))
            }
            None => false,
        };
        if same {
            return false;
        }
        let mut snapshot = self.clone();
        snapshot.last_rendered = None;
        self.last_rendered = Some(Box::new(snapshot));
        true
    }

    /// Force the next `ingest` (or an explicit render) to count as dirty.
    pub fn invalidate(&mut self) {
        self.last_rendered = None;
    }
}

fn level_pct(v: f32, warn: f32, crit: f32) -> Level {
    if v >= crit {
        Level::Crit
    } else if v >= warn {
        Level::Warn
    } else {
        Level::Normal
    }
}

/// Deterministic pretend data for development and spikes (no sampling needed).
pub fn fake_snapshot(tick: u64) -> Snapshot {
    let t = tick as f64;
    let wave = |period: f64, phase: f64| ((t / period + phase) * std::f64::consts::TAU).sin() * 0.5 + 0.5;
    let gib = 1_073_741_824u64;
    Snapshot {
        seq: tick,
        ok: true,
        cpu_pct: Some((8.0 + 60.0 * wave(23.0, 0.0)) as f32),
        ram_used: (8.2 * gib as f64 + 1.5 * gib as f64 * wave(41.0, 0.3)) as u64,
        ram_total: 16 * gib,
        gpu: GpuStat {
            source: GpuSource::Nvml,
            util_pct: Some((3.0 + 90.0 * wave(17.0, 0.6).powi(3)) as f32),
            vram_used: Some((1200.0 + 4000.0 * wave(31.0, 0.1)) as u64 * 1_048_576),
            vram_total: Some(12 * 1024 * 1_048_576),
            temp_c: Some(48 + (35.0 * wave(29.0, 0.2)) as u32),
            power_w: Some(40.0 + 200.0 * wave(17.0, 0.6).powi(3) as f32),
        },
        disks: vec![
            DiskStat { letter: "C:".into(), label: "Windows".into(), used_bytes: 567 * gib, total_bytes: 931 * gib },
            DiskStat { letter: "E:".into(), label: "Storage".into(), used_bytes: 468 * gib, total_bytes: 931 * gib },
        ],
        net_rx_bps: Some(20_000.0 + 12_000_000.0 * wave(13.0, 0.0).powi(4)),
        net_tx_bps: Some(5_000.0 + 900_000.0 * wave(19.0, 0.4).powi(2)),
        net_link_bps: Some(1_000_000_000),
        uptime_s: 97_320 + tick * 2,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn formats() {
        assert_eq!(fmt_pct(12.4), "12%");
        assert_eq!(fmt_pct(120.0), "100%");
        assert_eq!(fmt_ram(8_804_682_956, 17_179_869_184), "8.2 / 16 GB");
        assert_eq!(fmt_disk(567 * 1_073_741_824, 931 * 1_073_741_824), "567 / 931 GB");
        assert_eq!(fmt_bits(0.0), "0 Kbps");
        assert_eq!(fmt_bits(156_000.0), "1.25 Mbps");
        assert_eq!(fmt_bits(130_000_000.0), "1.04 Gbps");
        assert_eq!(fmt_bytes_rate(156_000.0), "152 KB/s");
        assert_eq!(fmt_bytes_rate(12_400_000.0), "11.8 MB/s");
        assert_eq!(fmt_uptime(97_320), "UP 1D 03H 02M");
        assert_eq!(fmt_uptime(3_720), "UP 01H 02M");
        assert_eq!(fmt_uptime(120), "UP 2M");
    }

    #[test]
    fn ring_keeps_order_and_capacity() {
        let mut r = Ring::new(3);
        for v in [1.0, 2.0, 3.0, 4.0] {
            r.push(v);
        }
        assert_eq!(r.iter().collect::<Vec<_>>(), vec![2.0, 3.0, 4.0]);
        assert_eq!(r.max(), 4.0);
        r.resize(2);
        assert_eq!(r.iter().collect::<Vec<_>>(), vec![3.0, 4.0]);
    }

    #[test]
    fn ingest_dirty_and_carry_forward() {
        let mut vm = ViewModel::new(false, 60);
        let s = fake_snapshot(1);
        assert!(vm.ingest(&s), "first ingest is dirty");
        assert!(!vm.ingest(&s), "identical snapshot is clean");
        let mut s2 = s.clone();
        s2.cpu_pct = None; // invalid baseline: keep the old CPU text
        s2.net_rx_bps = None;
        assert!(!vm.ingest(&s2));
        let cpu = &vm.sections[0].rows[0];
        assert_eq!(cpu.value, fmt_pct(s.cpu_pct.unwrap()));
        // sparklines on: every ingest with a new sample is dirty
        let mut vm2 = ViewModel::new(true, 60);
        assert!(vm2.ingest(&fake_snapshot(1)));
        assert!(vm2.ingest(&fake_snapshot(1)));
    }

    #[test]
    fn heights() {
        let mut vm = ViewModel::new(false, 60);
        vm.ingest(&fake_snapshot(1));
        // header 32 + pad 10 + 3 bands (60) + 2 gaps (20) + 7 rows (182) + 4 row gaps (32) + pad 10 + footer 26
        assert_eq!(vm.content_height(), 32.0 + 10.0 + 60.0 + 20.0 + 182.0 + 32.0 + 10.0 + 26.0);
        vm.sparklines = true;
        assert_eq!(vm.content_height(), 372.0 + 4.0 * theme::SPARK_EXTRA);
    }

    #[test]
    fn thresholds() {
        assert_eq!(level_pct(50.0, 85.0, 95.0), Level::Normal);
        assert_eq!(level_pct(90.0, 85.0, 95.0), Level::Warn);
        assert_eq!(level_pct(96.0, 85.0, 95.0), Level::Crit);
    }
}
