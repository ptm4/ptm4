//! Spike 6 — NVML FFI: load nvml.dll, sample utilization / VRAM / temperature / power ten
//! times at 1 s and time each call. Compare with `nvidia-smi --query-gpu=...`.
//! Pass: tracks Task Manager / nvidia-smi within ±10 points; each call < 1 ms; init < 300 ms.

use std::time::Instant;

use ptmonitor2::sample::gpu_nvml::Nvml;
use ptmonitor2::sample::gpu_pdh::Pdh;

fn main() {
    let t0 = Instant::now();
    let nvml = Nvml::init();
    println!("nvml init: {:?} in {:.1} ms", nvml.as_ref().map(|n| n.name.clone()), t0.elapsed().as_secs_f64() * 1000.0);
    if let Some(mut n) = nvml {
        for i in 0..10 {
            let t = Instant::now();
            let s = n.sample();
            let dt = t.elapsed().as_secs_f64() * 1000.0;
            match s {
                Some(s) => println!(
                    "#{i:<2} util {:>3}%  vram {:>5} / {:>5} MiB  temp {:>2}°C  power {:>5.1} W   ({dt:.3} ms)",
                    s.util_pct.unwrap_or(0.0),
                    s.vram_used.unwrap_or(0) / 1_048_576,
                    s.vram_total.unwrap_or(0) / 1_048_576,
                    s.temp_c.unwrap_or(0),
                    s.power_w.unwrap_or(0.0)
                ),
                None => println!("#{i} sample failed"),
            }
            std::thread::sleep(std::time::Duration::from_secs(1));
        }
    }
    let t1 = Instant::now();
    let pdh = Pdh::init();
    println!("pdh init: {} in {:.1} ms", pdh.is_some(), t1.elapsed().as_secs_f64() * 1000.0);
    if let Some(mut p) = pdh {
        for i in 0..5 {
            std::thread::sleep(std::time::Duration::from_secs(1));
            let t = Instant::now();
            let s = p.sample();
            println!("pdh #{i} util {:?}  ({:.3} ms)", s.and_then(|s| s.util_pct), t.elapsed().as_secs_f64() * 1000.0);
        }
    }
}
