//! Vendor-neutral GPU utilization from the `GPU Engine` performance counters (what Task
//! Manager uses): one persistent PDH query, collected every tick; the headline value is the
//! maximum over engine types of the per-type sum, clamped to 100.

use windows::core::w;
use windows::Win32::System::Performance::{
    PdhAddEnglishCounterW, PdhCloseQuery, PdhCollectQueryData, PdhGetFormattedCounterArrayW,
    PdhOpenQueryW, PDH_FMT_COUNTERVALUE_ITEM_W, PDH_FMT_DOUBLE, PDH_HCOUNTER, PDH_HQUERY,
    PDH_MORE_DATA,
};

use crate::model::{GpuSource, GpuStat};
use crate::util::from_wide;

pub struct Pdh {
    query: PDH_HQUERY,
    counter: PDH_HCOUNTER,
    buf: Vec<u8>,
    primed: bool,
}

unsafe impl Send for Pdh {}

impl Pdh {
    pub fn init() -> Option<Pdh> {
        let mut query = PDH_HQUERY::default();
        let mut counter = PDH_HCOUNTER::default();
        // SAFETY: PDH handles are opaque; strings are static.
        unsafe {
            if PdhOpenQueryW(None, 0, &mut query) != 0 {
                return None;
            }
            if PdhAddEnglishCounterW(query, w!("\\GPU Engine(*)\\Utilization Percentage"), 0, &mut counter) != 0 {
                let _ = PdhCloseQuery(query);
                return None;
            }
            // First collection is a baseline: rate counters need two samples.
            let _ = PdhCollectQueryData(query);
        }
        Some(Pdh { query, counter, buf: vec![0u8; 64 * 1024], primed: false })
    }

    pub fn sample(&mut self) -> Option<GpuStat> {
        // SAFETY: PDH calls on our handles; the buffer is grown to the size PDH asks for.
        unsafe {
            if PdhCollectQueryData(self.query) != 0 {
                return None;
            }
            if !self.primed {
                self.primed = true;
                return Some(GpuStat { source: GpuSource::Pdh, ..Default::default() });
            }
            let mut size = self.buf.len() as u32;
            let mut count = 0u32;
            let mut rc = PdhGetFormattedCounterArrayW(
                self.counter,
                PDH_FMT_DOUBLE,
                &mut size,
                &mut count,
                Some(self.buf.as_mut_ptr() as *mut PDH_FMT_COUNTERVALUE_ITEM_W),
            );
            if rc == PDH_MORE_DATA {
                self.buf.resize(size as usize + 1024, 0);
                size = self.buf.len() as u32;
                rc = PdhGetFormattedCounterArrayW(
                    self.counter,
                    PDH_FMT_DOUBLE,
                    &mut size,
                    &mut count,
                    Some(self.buf.as_mut_ptr() as *mut PDH_FMT_COUNTERVALUE_ITEM_W),
                );
            }
            if rc != 0 {
                return None;
            }
            let items = std::slice::from_raw_parts(self.buf.as_ptr() as *const PDH_FMT_COUNTERVALUE_ITEM_W, count as usize);
            // Sum per engine type, take the busiest type (Task Manager semantics).
            let mut per_type: Vec<(String, f64)> = Vec::new();
            for it in items {
                if it.szName.is_null() {
                    continue;
                }
                let name = from_wide(it.szName.as_wide());
                let engtype = name.rsplit("engtype_").next().unwrap_or("").to_string();
                let v = it.FmtValue.Anonymous.doubleValue;
                match per_type.iter_mut().find(|(t, _)| *t == engtype) {
                    Some((_, sum)) => *sum += v,
                    None => per_type.push((engtype, v)),
                }
            }
            let max = per_type.iter().map(|(_, v)| *v).fold(0.0, f64::max);
            Some(GpuStat { source: GpuSource::Pdh, util_pct: Some(max.clamp(0.0, 100.0) as f32), ..Default::default() })
        }
    }
}

impl Drop for Pdh {
    fn drop(&mut self) {
        // SAFETY: closing our own query.
        unsafe {
            let _ = PdhCloseQuery(self.query);
        }
    }
}
