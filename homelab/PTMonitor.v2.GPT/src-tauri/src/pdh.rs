//! Language-neutral native PDH counters. Read wildcard arrays each tick to see new processes.
use std::collections::HashMap;
use windows_sys::Win32::System::Performance::{
    PdhAddEnglishCounterW, PdhCloseQuery, PdhCollectQueryData, PdhGetFormattedCounterArrayW,
    PdhGetFormattedCounterValue, PdhOpenQueryW, PDH_CSTATUS_NEW_DATA, PDH_CSTATUS_VALID_DATA,
    PDH_FMT_COUNTERVALUE, PDH_FMT_COUNTERVALUE_ITEM_W, PDH_FMT_DOUBLE, PDH_MORE_DATA,
};

// Pdh.h macro omitted from windows-sys metadata (Windows SDK 10.0.26100.0).
const PDH_FMT_NOCAP100: u32 = 0x0000_8000;

pub struct PdhGauge {
    query: isize,
    counter: isize,
    wildcard: bool,
    pub last_error: Option<String>,
}

impl PdhGauge {
    pub fn new(counter_path: &str) -> Result<Self, String> {
        let mut query = 0;
        let status = unsafe { PdhOpenQueryW(std::ptr::null(), 0, &mut query) };
        if status != 0 {
            return Err(format!("open PDH query ({status:#x})"));
        }
        let path = wide(counter_path);
        let mut counter = 0;
        // Localize object/counter names, retain wildcard for dynamic array discovery.
        let status = unsafe { PdhAddEnglishCounterW(query, path.as_ptr(), 0, &mut counter) };
        if status != 0 {
            unsafe { PdhCloseQuery(query) };
            return Err(format!("PDH unavailable ({status:#x}): {counter_path}"));
        }
        unsafe { PdhCollectQueryData(query) };
        Ok(Self {
            query,
            counter,
            wildcard: counter_path.contains('*'),
            last_error: None,
        })
    }

    fn collect(&mut self) -> bool {
        let status = unsafe { PdhCollectQueryData(self.query) };
        self.last_error = (status != 0).then(|| format!("collect PDH ({status:#x})"));
        status == 0
    }

    pub fn sample_sum(&mut self) -> Option<f64> {
        if self.wildcard {
            let values = self.sample_instances()?;
            return (!values.is_empty()).then(|| values.iter().map(|(_, value)| value).sum());
        }
        if !self.collect() {
            return None;
        }
        let mut kind = 0;
        let mut value: PDH_FMT_COUNTERVALUE = unsafe { std::mem::zeroed() };
        let status = unsafe {
            PdhGetFormattedCounterValue(
                self.counter,
                PDH_FMT_DOUBLE | PDH_FMT_NOCAP100,
                &mut kind,
                &mut value,
            )
        };
        if status != 0 {
            self.last_error = Some(format!("format PDH ({status:#x})"));
            return None;
        }
        valid_value(&value)
    }

    pub fn sample_gpu(&mut self) -> Option<f64> {
        busiest_gpu_engine(&self.sample_instances()?)
    }

    fn sample_instances(&mut self) -> Option<Vec<(String, f64)>> {
        if !self.collect() {
            return None;
        }
        // A growing instance list requires re-sizing from zero; PDH's failed-call size
        // is not reliable. Keep retries/memory bounded if a provider misbehaves.
        for _ in 0..3 {
            let mut bytes = 0;
            let mut count = 0;
            let status = unsafe {
                PdhGetFormattedCounterArrayW(
                    self.counter,
                    PDH_FMT_DOUBLE | PDH_FMT_NOCAP100,
                    &mut bytes,
                    &mut count,
                    std::ptr::null_mut(),
                )
            };
            if status != PDH_MORE_DATA || bytes == 0 || bytes > 32 * 1024 * 1024 {
                self.last_error = Some(format!("size PDH array ({status:#x})"));
                return None;
            }
            // u64 storage aligns the native pointer/double fields.
            let mut buffer = vec![0u64; (bytes as usize).div_ceil(8)];
            let capacity = buffer.len() * 8;
            let items = buffer.as_mut_ptr().cast::<PDH_FMT_COUNTERVALUE_ITEM_W>();
            let status = unsafe {
                PdhGetFormattedCounterArrayW(
                    self.counter,
                    PDH_FMT_DOUBLE | PDH_FMT_NOCAP100,
                    &mut bytes,
                    &mut count,
                    items,
                )
            };
            if status == PDH_MORE_DATA {
                continue;
            }
            if status != 0
                || count as usize > capacity / std::mem::size_of::<PDH_FMT_COUNTERVALUE_ITEM_W>()
            {
                self.last_error = Some(format!("read PDH array ({status:#x})"));
                return None;
            }
            let start = buffer.as_ptr() as usize;
            let end = start + capacity;
            let mut result = Vec::with_capacity(count as usize);
            for item in unsafe { std::slice::from_raw_parts(items, count as usize) } {
                let Some(value) = valid_value(&item.FmtValue) else {
                    continue;
                };
                let address = item.szName as usize;
                if address < start || address >= end || !address.is_multiple_of(2) {
                    continue;
                }
                let name = unsafe { std::slice::from_raw_parts(item.szName, (end - address) / 2) };
                let len = name
                    .iter()
                    .position(|value| *value == 0)
                    .unwrap_or(name.len());
                result.push((String::from_utf16_lossy(&name[..len]), value));
            }
            self.last_error = None;
            return Some(result);
        }
        self.last_error = Some("PDH instance list kept changing; next sample will retry".into());
        None
    }
}

impl Drop for PdhGauge {
    fn drop(&mut self) {
        unsafe { PdhCloseQuery(self.query) };
    }
}

fn valid_value(value: &PDH_FMT_COUNTERVALUE) -> Option<f64> {
    if !matches!(value.CStatus, PDH_CSTATUS_VALID_DATA | PDH_CSTATUS_NEW_DATA) {
        return None;
    }
    let number = unsafe { value.Anonymous.doubleValue };
    (number.is_finite() && number >= 0.0).then_some(number)
}

/// Task Manager semantics: sum process contributions within a physical GPU engine,
/// then take the busiest engine. Adding 3D + Copy + Video overstates utilization.
fn busiest_gpu_engine(instances: &[(String, f64)]) -> Option<f64> {
    let mut engines: HashMap<&str, f64> = HashMap::new();
    for (name, value) in instances {
        if !value.is_finite() || *value < 0.0 {
            continue;
        }
        let Some(start) = name.find("luid_") else {
            continue;
        };
        let key = name[start..].split("_engtype_").next().unwrap_or_default();
        if !key.contains("_phys_") || !key.contains("_eng_") {
            continue;
        }
        *engines.entry(key).or_default() += value;
    }
    engines
        .values()
        .copied()
        .reduce(f64::max)
        .map(|value| value.clamp(0.0, 100.0))
}

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    fn instance(pid: u32, gpu: u32, engine: u32, value: f64) -> (String, f64) {
        (
            format!("pid_{pid}_luid_0x00000000_0x{gpu:08x}_phys_0_eng_{engine}_engtype_3D"),
            value,
        )
    }
    #[test]
    fn sums_processes_but_not_engines_or_gpus() {
        assert_eq!(
            busiest_gpu_engine(&[
                instance(1, 1, 0, 30.0),
                instance(2, 1, 0, 40.0),
                instance(1, 1, 1, 55.0),
                instance(1, 2, 0, 60.0),
            ]),
            Some(70.0)
        );
    }
    #[test]
    fn unavailable_is_distinct_from_idle() {
        assert_eq!(busiest_gpu_engine(&[]), None);
        assert_eq!(busiest_gpu_engine(&[instance(1, 1, 0, 0.0)]), Some(0.0));
        assert_eq!(busiest_gpu_engine(&[instance(1, 1, 0, f64::NAN)]), None);
    }
    #[test]
    fn engine_sampling_overlap_never_exceeds_one_hundred() {
        assert_eq!(
            busiest_gpu_engine(&[instance(1, 1, 0, 80.0), instance(2, 1, 0, 40.0)]),
            Some(100.0)
        );
    }
}
