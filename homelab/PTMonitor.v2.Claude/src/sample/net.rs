//! Network throughput from `GetIfTable2` octet deltas. Auto mode counts hardware interfaces
//! that are connected and up (this excludes loopback, tunnels, Hyper-V/WSL vEthernet);
//! an alias whitelist overrides. Negative deltas (counter reset) yield `None`.

use windows::Win32::NetworkManagement::IpHelper::{FreeMibTable, GetIfTable2, MIB_IF_TABLE2};
use windows::Win32::NetworkManagement::Ndis::{IfOperStatusUp, MediaConnectStateConnected};

use crate::sample::cpu_mem::SampleError;
use crate::util::from_wide;

const IF_TYPE_SOFTWARE_LOOPBACK: u32 = 24;
const IF_TYPE_TUNNEL: u32 = 131;

pub struct Net {
    prev: Option<(u64, u64)>,
    pub whitelist: Option<Vec<String>>,
    pub selected: Vec<String>,
}

pub struct NetSample {
    pub rx_bps: Option<f64>,
    pub tx_bps: Option<f64>,
    pub link_bps: Option<u64>,
}

impl Net {
    pub fn new(whitelist: Option<Vec<String>>) -> Self {
        Net { prev: None, whitelist, selected: Vec::new() }
    }

    pub fn reset(&mut self) {
        self.prev = None;
    }

    pub fn sample(&mut self, elapsed_s: f64) -> Result<NetSample, SampleError> {
        let mut table: *mut MIB_IF_TABLE2 = std::ptr::null_mut();
        // SAFETY: GetIfTable2 allocates the table; FreeMibTable releases it after we copy what we need.
        let (rx, tx, link, names) = unsafe {
            if GetIfTable2(&mut table).is_err() || table.is_null() {
                return Err(SampleError);
            }
            let t = &*table;
            let rows = std::slice::from_raw_parts(t.Table.as_ptr(), t.NumEntries as usize);
            let (mut rx, mut tx, mut link) = (0u64, 0u64, 0u64);
            let mut names = Vec::new();
            for r in rows {
                let alias = from_wide(&r.Alias);
                let hardware = r.InterfaceAndOperStatusFlags._bitfield & 1 != 0;
                let selected = match &self.whitelist {
                    Some(list) => list.iter().any(|w| w.eq_ignore_ascii_case(&alias)),
                    None => {
                        hardware
                            && r.OperStatus == IfOperStatusUp
                            && r.MediaConnectState == MediaConnectStateConnected
                            && r.Type != IF_TYPE_SOFTWARE_LOOPBACK
                            && r.Type != IF_TYPE_TUNNEL
                    }
                };
                if selected {
                    rx += r.InOctets;
                    tx += r.OutOctets;
                    link = link.max(r.ReceiveLinkSpeed);
                    names.push(alias);
                }
            }
            FreeMibTable(table as *const _);
            (rx, tx, link, names)
        };
        self.selected = names;
        let out = match self.prev {
            Some((prx, ptx)) if elapsed_s > 0.0 && rx >= prx && tx >= ptx => NetSample {
                rx_bps: Some((rx - prx) as f64 / elapsed_s),
                tx_bps: Some((tx - ptx) as f64 / elapsed_s),
                link_bps: (link > 0).then_some(link),
            },
            _ => NetSample { rx_bps: None, tx_bps: None, link_bps: (link > 0).then_some(link) },
        };
        self.prev = Some((rx, tx));
        Ok(out)
    }
}
