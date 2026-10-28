Native camera backend · Windows test branch

The GUI now imports `gui/native_bridge.py`, which runs `native/camera.py` directly on the Mac through ARM64 libusb/IOKit. No Linux process, virtual machine, or vendor host SDK is used at runtime. The instrument still runs its own vendor firmware, uploaded into volatile RAM by the native backend.

Verified on USB 1409:3370, sensor UI337xCP-M, serial 4110057336:
- Cold firmware upload, RAM readback verification and USB re-enumeration.
- FPGA configuration and camera initialization with checked acknowledgements. Two known unsupported capability probes are accepted only when they match the successful vendor trace; unexpected errors stop acquisition.
- Complete 2048×2048 mono frames: 56-byte leader, 4,194,304 pixel bytes, 60-byte metadata chunk and 32-byte trailer.
- Advancing device timestamps and sensor counters, plus continuous display in the existing GUI with no QEMU process.
- Recorded-frame decoder tests and rejection of invalid boundaries.

This first backend uses the instrument-specific startup sequence recorded from the vendor driver. It is restricted to serial 4110057336. Its firmware and recipe stay local to this instrument's workspace. A fresh start currently reloads the device configuration; allow approximately 15 seconds.

Current controls: native exposure requests of 0.04–150 ms and FPGA digital master gain of 0–100% (1×–4×). `Camera.set_controls` uses the captured full-resolution timing template, updates only integration registers and the exposure tag, preserves frame blanking/clock, and validates every acknowledgement. Applied exposure accounts for the 12.9 µs quantization. Live checks verified 0.29 ms requested → 0.285735 ms applied, plus a 2.5× gain setting and restoration to nominal 10 ms / unity gain. Commands are issued between frames by the capture owner. These do not modify factory memory.

From the repository root, run `python gui/app.py`, then open http://127.0.0.1:8864.

Hardware probe (close/stop the GUI camera first):
`python native/camera.py --frames 3`

Protocol checks without hardware:
`python -m unittest discover -s native -p test_protocol.py`

The older VM backend and its disk are retained for development comparison but are not launched by the GUI.

Restart limitation discovered during benchmarking: switching backends or reopening the camera can leave an incomplete FPGA configuration and require a physical USB reconnect. Startup now detects that condition and checks the FPGA identifier before reusing an existing configuration; automatic recovery is not yet verified. See ../docs/benchmark.md for measured performance.

Windows x64 support is implemented on `codex/windows-support`, pending hardware validation. The transport is `usb_transport.py`; `libusb_loader.py` resolves the platform library without loading USB at import. Use `python native/doctor.py --offline` for a software check or `--usb` for read-only enumeration. See [Windows setup](../docs/windows_setup.md). The normal command on both platforms is `python gui/app.py` from the repo root.
