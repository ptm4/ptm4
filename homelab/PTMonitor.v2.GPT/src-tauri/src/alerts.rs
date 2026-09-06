//! Sustained-condition alerts with hysteresis. The timeline lives in native memory,
//! so hiding or reloading the dashboard cannot lose transitions or create duplicates.
use crate::{config::Thresholds, stats::Snapshot};
use serde::Serialize;
use std::collections::{BTreeMap, HashSet, VecDeque};

#[derive(Debug, Clone, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct Alert {
    pub key: String,
    pub level: String,
    pub message: String,
    pub captured_at_ms: u64,
}

#[derive(Clone, Copy, Default, PartialEq, Eq)]
enum Severity {
    #[default]
    Normal,
    Warning,
    Critical,
}
impl Severity {
    fn label(self) -> &'static str {
        match self {
            Self::Normal => "resolved",
            Self::Warning => "warning",
            Self::Critical => "critical",
        }
    }
}
#[derive(Default)]
struct Condition {
    active: Severity,
    pending: Severity,
    pending_since_ms: u64,
    activated_at_ms: u64,
}

struct Measurement {
    key: String,
    label: String,
    value: f64,
    unit: &'static str,
    warn: f64,
    critical: f64,
    sustain_ms: u64,
}

#[derive(Default)]
pub struct AlertEngine {
    conditions: BTreeMap<String, Condition>,
    history: VecDeque<Alert>,
    last_evaluation_ms: Option<u64>,
}

impl AlertEngine {
    pub fn evaluate(
        &mut self,
        snapshot: &Snapshot,
        thresholds: &Thresholds,
        elapsed_ms: u64,
    ) -> Vec<Alert> {
        self.evaluate_measurements(
            measurements(snapshot, thresholds),
            elapsed_ms,
            snapshot.captured_at_ms,
        )
    }

    pub fn history(&self) -> Vec<Alert> {
        self.history.iter().cloned().collect()
    }

    fn record(&mut self, alert: Alert) {
        self.history.push_front(alert);
        self.history.truncate(100);
    }

    fn evaluate_measurements(
        &mut self,
        measurements: Vec<Measurement>,
        elapsed_ms: u64,
        wall_ms: u64,
    ) -> Vec<Alert> {
        // Suspend/collector gaps are unobserved time, not evidence of a sustained
        // condition. Require a fresh dwell period after resuming collection.
        if self
            .last_evaluation_ms
            .is_some_and(|last| elapsed_ms.saturating_sub(last) > 5_000)
        {
            for state in self.conditions.values_mut() {
                state.pending_since_ms = elapsed_ms;
            }
        }
        self.last_evaluation_ms = Some(elapsed_ms);
        let mut active = Vec::new();
        let mut seen = HashSet::new();
        let mut transitions = Vec::new();
        for reading in measurements {
            if !reading.value.is_finite() {
                continue;
            }
            seen.insert(reading.key.clone());
            let state = self.conditions.entry(reading.key.clone()).or_default();
            let target = if reading.value >= reading.critical
                || (state.active == Severity::Critical && reading.value >= reading.critical - 3.0)
            {
                Severity::Critical
            } else if reading.value >= reading.warn
                || (state.active != Severity::Normal && reading.value >= reading.warn - 3.0)
            {
                Severity::Warning
            } else {
                Severity::Normal
            };
            if target != state.pending {
                state.pending = target;
                state.pending_since_ms = elapsed_ms;
            }
            let dwell = if target == Severity::Normal {
                5_000
            } else {
                reading.sustain_ms
            };
            let changed = target != state.active
                && elapsed_ms.saturating_sub(state.pending_since_ms) >= dwell;
            if changed {
                state.active = target;
                state.activated_at_ms = wall_ms;
            }
            let message = format!("{} {:.0}{}", reading.label, reading.value, reading.unit);
            if changed {
                transitions.push(Alert {
                    key: reading.key.clone(),
                    level: state.active.label().into(),
                    message: if target == Severity::Normal {
                        format!("{message} — recovered")
                    } else {
                        message.clone()
                    },
                    captured_at_ms: wall_ms,
                });
            }
            if state.active != Severity::Normal {
                active.push(Alert {
                    key: reading.key,
                    level: state.active.label().into(),
                    message,
                    captured_at_ms: state.activated_at_ms,
                });
            }
        }
        self.conditions.retain(|key, state| {
            if !seen.contains(key) && state.active != Severity::Normal {
                transitions.push(Alert {
                    key: key.clone(),
                    level: "unavailable".into(),
                    message: "Reading became unavailable; condition can no longer be evaluated"
                        .into(),
                    captured_at_ms: wall_ms,
                });
            }
            seen.contains(key)
        });
        for transition in transitions {
            self.record(transition);
        }
        active.sort_by(|a, b| a.level.cmp(&b.level).then_with(|| a.key.cmp(&b.key)));
        active
    }
}

fn measurements(snapshot: &Snapshot, t: &Thresholds) -> Vec<Measurement> {
    let mut result = Vec::new();
    let mut push = |key: String, label: String, value: f64, unit, warn, critical, sustain_ms| {
        result.push(Measurement {
            key,
            label,
            value,
            unit,
            warn,
            critical,
            sustain_ms,
        });
    };
    push(
        "cpu".into(),
        "CPU load".into(),
        snapshot.cpu.usage_pct,
        "%",
        t.cpu_warn_pct,
        t.cpu_critical_pct,
        10_000,
    );
    push(
        "memory".into(),
        "Memory load".into(),
        snapshot.memory.usage_pct,
        "%",
        t.ram_warn_pct,
        t.ram_critical_pct,
        10_000,
    );
    if let Some(value) = snapshot.gpu.usage_pct {
        push(
            "gpu".into(),
            "GPU load".into(),
            value,
            "%",
            t.gpu_warn_pct,
            t.gpu_critical_pct,
            10_000,
        );
    }
    if let Some(value) = snapshot.cpu.temp_c {
        push(
            "cpu_temp".into(),
            "CPU temperature".into(),
            value,
            "°C",
            t.cpu_temp_warn_c,
            t.cpu_temp_critical_c,
            5_000,
        );
    }
    if let Some(value) = snapshot.gpu.temp_c {
        push(
            "gpu_temp".into(),
            "GPU temperature".into(),
            value,
            "°C",
            t.gpu_temp_warn_c,
            t.gpu_temp_critical_c,
            5_000,
        );
    }
    for disk in &snapshot.disks {
        push(
            format!("disk_{}", disk.id),
            format!("{} capacity", disk.label),
            disk.usage_pct,
            "%",
            t.disk_warn_pct,
            t.disk_critical_pct,
            30_000,
        );
    }
    for sensor in &snapshot.storage_temps {
        push(
            format!("disk_temp_{}", sensor.id),
            format!("{} {}", sensor.hardware, sensor.name),
            sensor.value,
            "°C",
            t.disk_temp_warn_c,
            t.disk_temp_critical_c,
            5_000,
        );
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    fn temperature(value: f64) -> Vec<Measurement> {
        vec![Measurement {
            key: "cpu_temp".into(),
            label: "CPU temperature".into(),
            value,
            unit: "°C",
            warn: 85.0,
            critical: 95.0,
            sustain_ms: 5_000,
        }]
    }
    #[test]
    fn sustained_temperature_has_correct_units_and_one_transition() {
        let mut engine = AlertEngine::default();
        assert!(engine
            .evaluate_measurements(temperature(96.0), 0, 1000)
            .is_empty());
        assert!(engine
            .evaluate_measurements(temperature(96.0), 4999, 5999)
            .is_empty());
        let alerts = engine.evaluate_measurements(temperature(96.0), 5000, 6000);
        assert_eq!(alerts[0].message, "CPU temperature 96°C");
        assert_eq!(alerts[0].level, "critical");
        engine.evaluate_measurements(temperature(97.0), 6000, 7000);
        assert_eq!(engine.history.len(), 1);
    }
    #[test]
    fn spikes_reset_dwell_and_hysteresis_prevents_flapping() {
        let mut engine = AlertEngine::default();
        engine.evaluate_measurements(temperature(87.0), 0, 0);
        engine.evaluate_measurements(temperature(80.0), 4000, 4000);
        assert!(engine
            .evaluate_measurements(temperature(87.0), 5000, 5000)
            .is_empty());
        engine.evaluate_measurements(temperature(87.0), 10000, 10000);
        assert_eq!(
            engine
                .evaluate_measurements(temperature(83.0), 11000, 11000)
                .len(),
            1
        );
        engine.evaluate_measurements(temperature(80.0), 12000, 12000);
        assert!(engine
            .evaluate_measurements(temperature(80.0), 17000, 17000)
            .is_empty());
        assert_eq!(engine.history()[0].level, "resolved");
    }
    #[test]
    fn unavailable_readings_clear_active_state_and_history_is_bounded() {
        let mut engine = AlertEngine::default();
        engine.evaluate_measurements(temperature(96.0), 0, 0);
        engine.evaluate_measurements(temperature(96.0), 5000, 5000);
        assert!(engine.evaluate_measurements(vec![], 6000, 6000).is_empty());
        assert!(engine.history()[0].message.contains("unavailable"));
        assert_eq!(engine.history()[0].level, "unavailable");
        for i in 0..200 {
            engine.record(Alert {
                captured_at_ms: i,
                ..Alert::default()
            });
        }
        assert_eq!(engine.history.len(), 100);
        assert_eq!(engine.history()[0].captured_at_ms, 199);
    }

    #[test]
    fn suspended_time_does_not_count_toward_sustained_alerts() {
        let mut engine = AlertEngine::default();
        engine.evaluate_measurements(temperature(96.0), 0, 0);
        assert!(engine
            .evaluate_measurements(temperature(96.0), 60_000, 60_000)
            .is_empty());
        assert_eq!(
            engine
                .evaluate_measurements(temperature(96.0), 65_000, 65_000)
                .len(),
            1
        );
    }
}
