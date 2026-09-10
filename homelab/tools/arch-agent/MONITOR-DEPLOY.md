# Monitor agent deployment

The Monitor page collects detail from each host agent every two seconds while a
browser has the page open. Deploy `monitor.py` beside `hl-arch-agent.py` on opti,
rpi, and noblenumbat; the import is local and requires no Python packages.

1. Confirm the service has a backup and copy both source files to
   `/usr/local/bin/` with executable permission on `hl-arch-agent.py`.
2. On opti and noblenumbat, install `intel-gpu-tools` if `intel_gpu_top` is desired
   for future GPU expansion. The current collector reports the kernel-supported GPU
   fields without starting that command.
3. Restart `hl-arch-agent.service`, then verify authenticated `GET
   /monitor/capabilities` and `GET /monitor/snapshot` return JSON.
4. Open `/monitor`; its footer must read `fresh collection every 2s`. Confirm all
   three hosts produce a fresh sample, and try a harmless process-detail request.

The app never starts the two-second sampler when Monitor has no active client. A
process signal is token-gated at the host, validates boot ID and process start time,
uses a pidfd, and creates a dashboard job audit record.
