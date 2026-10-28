# Native macOS vs Linux/VM camera benchmark

Measured on this Mac and sensor 4110057336, using 2048×2048 mono 8-bit frames, nominal 10 ms exposure, 0% gain, 30 measured frames after 4 warm-up frames. The viewer's normal 2 fps throttle was disabled. Wavefront analysis and browser rendering were excluded.

| Metric | Native macOS | Linux/QEMU |
|---|---:|---:|
| Backend start → first full frame | 13.63 s | 45.71 s |
| Full frames published to host | 13.45 fps | 11.44 fps |
| Capture call median | 70.1 ms | 55.0 ms |
| Capture call 95th percentile | 76.8 ms | 66.7 ms |
| Acquisition CPU (100% = one core) | 35% | 100% |
| Acquisition resident memory | 77 MiB | 1085 MiB |

Native delivered 18% more published frames per second, reached the first frame 3.4× faster, and used 14.1× less resident memory in this run.

The SDK capture call itself was faster than the native command sequence; the VM path then incurred more overhead publishing each 4 MiB frame through the guest's shared filesystem. Native capture includes its current defensive USB command delays and logging. These are measurements of the current implementations, not maximum sensor frame rate or optimized streaming drivers.

Startup is backend launch to the first complete frame and includes VM boot/automatic USB initialization. It is not a physical USB power-cycle test. Each measurement started a fresh backend instance and performed device initialization. The runs were sequential (VM first, native second). Startup has one sample per backend. Steady acquisition has 30 samples over about 2–3 seconds per backend, so CPU/memory figures are approximate rather than long-duration averages. Memory and CPU cover the benchmark host process plus QEMU when present; the common GUI server/browser and wavefront analysis are excluded. Guest SDK reported 5.0 fps from its configuration call; the one-frame trigger path nevertheless delivered the rates above. Do not interpret that SDK setting as a measured frame-rate ceiling.

The comparison exposed a native warm-start problem: a completed FPGA configuration must be detected and reused rather than blindly uploaded again. Native startup now checks the FPGA state and identifier before choosing that path, and detects incomplete configuration. Warm-start recovery is still unresolved: restoring the viewer required another physical USB reconnect. The viewer was then verified streaming natively again.

Raw timings, frame metadata and resource samples are in [benchmark_results.json](benchmark_results.json). Run with USB access from the repository root: `python -u benchmark.py --frames 30 --backends vm native`.
