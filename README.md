# Native macOS wavefront sensor viewer

Direct USB acquisition on an Apple Silicon Mac for a Thorlabs wavefront sensor containing an IDS UI337xCP-M camera. The default backend runs through macOS libusb/IOKit, with **no Linux VM or vendor host SDK at runtime**.

This is a working instrument-specific prototype, tested with USB ID `1409:3370`, serial `4110057336`, at 2048 × 2048 monochrome 8-bit resolution and 5.5 µm pixel pitch. It is not a general replacement for the Thorlabs or IDS SDK.

## What works

- Native volatile firmware loading with RAM readback verification, FPGA configuration, and checked command acknowledgements.
- Live raw camera preview, currently displayed at about two updates per second.
- Detection of Shack–Hartmann spots above an adjustable intensity/noise threshold.
- Relative wavefront reconstruction by fitting 14 Zernike gradient modes to spot displacements from a measured reference.
- Optional removal of fitted tip/tilt from the displayed wavefront; piston is removed.
- Wavefront and metrics hidden on dark, stale, saturated, diagnostic, or otherwise invalid data.
- Local comparison tooling for the native and earlier Linux/QEMU backends.

## Important limits

- Native exposure is currently fixed at nominal **10 ms**, with **0% gain**. Those GUI controls are disabled until their native commands are verified.
- Switching backends or reopening the camera can leave incomplete FPGA configuration and require a physical USB reconnect. Startup detects this condition; automatic recovery remains unfinished.
- A fresh native start took about 14 seconds in the measured run. This is not yet an optimized streaming driver.
- The native backend is restricted to the tested instrument serial. Support for other instruments requires protocol and calibration validation.
- Optical wavefront accuracy under calibrated illumination has not yet been validated. Synthetic defocus recovery and recorded USB frame decoding have been tested.
- Tip/tilt removal is currently controlled by a checkbox; an angular tip/tilt readout and a configurable “remove only when small” gate remain future work.

## Local firmware dependency

**A source-only checkout cannot acquire images by itself.** Native capture also needs `native/recipe.json.gz`, which contains this instrument's recorded startup commands and vendor firmware payloads. The working local copy already has it; it is deliberately excluded from Git, along with the original USB traces, VM disk, captured images, and calibration data.

`native/extract_recipe.py` can regenerate that recipe from the original local `native/usb_trace_initial.bin`. Its packet ranges are specific to that recording; it is not a general trace importer. Keep these local files available when moving this working setup to another computer.

## Setup

Tested on Apple Silicon macOS with Python 3.12 and Homebrew libusb at `/opt/homebrew/lib/libusb-1.0.dylib`.

From the repository root:

```sh
brew install libusb
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The firmware recipe described above must also be present. The native backend needs direct access to the USB device; a restricted execution environment may prevent enumeration. Only one process should own the sensor at a time.

## Run

```sh
source .venv/bin/activate
python gui/app.py
```

Open **http://127.0.0.1:8864**. The server binds only to the local Mac.

Alternatively, double-click `open_viewer.command`. It opens an existing viewer if available; otherwise it uses `.venv/bin/python`. Set `WFS_PYTHON` to select another Python environment. An ignored local `runtime/python_path` can also select the interpreter for this working copy.

If startup reports incomplete FPGA configuration, unplug and reconnect the sensor, then press **Start**. Avoid running the standalone hardware probe while the GUI camera is active.

## Wavefront analysis

1. Illuminate the sensor with a known flat reference wavefront.
2. Adjust the spot threshold and minimum usable spot count.
3. Enter the focal length of the mounted microlens array in millimetres.
4. Press **Set flat reference**.
5. Measure subsequent changes relative to that reference. Select **Remove tip / tilt** if desired.

The local slope model is `slope = spot_displacement / lenslet_focal_length`, using consistent physical units. Zernike derivatives are fitted to these slopes. Output is optical path difference in micrometres over the measured pupil coverage. No factory lenslet reference or focal length is assumed. A reference measured under an aberrated beam defines that aberration as the relative zero.

## Tests

```sh
python -m unittest discover -s gui -p 'test_analysis.py'
python -m unittest discover -s native -p 'test_protocol.py'
```

The first suite checks synthetic defocus recovery and signal/calibration gates without hardware. The second checks decoding and rejection of incomplete recorded frames; it skips when the untracked instrument trace is unavailable.

For a standalone hardware capture, stop the GUI camera first:

```sh
python native/camera.py --frames 3
```

This writes raw PGM frames and metadata under the ignored `captures/native/` directory.

## Measured performance

One sequential comparison on this Mac, 30 full-resolution frames per backend after four warm-up frames, with the normal GUI throttle disabled:

| Metric | Native macOS | Linux/QEMU |
|---|---:|---:|
| Backend start to first frame | 13.6 s | 45.7 s |
| Full frames published to host | 13.5 fps | 11.4 fps |
| Backend CPU, 100% = one core | 35% | 100% |
| Backend resident memory | 77 MiB | 1,085 MiB |

These compare the current acquisition implementations, excluding browser rendering and wavefront analysis. They are not maximum sensor specifications or long-duration averages. See [benchmark details](docs/benchmark.md) and [recorded measurements](docs/benchmark_results.json).

To repeat the comparison, the optional VM runtime `runtime/driver.qcow2`, its installed vendor SDK, QEMU, and the macOS USB recovery shim must also be available. Those dependencies are not needed for normal native operation and are not included in Git.

```sh
python -u benchmark.py --frames 30 --backends vm native
```

The comparison pauses the viewer, uses the sensor exclusively, saves results under `diagnostics/`, and attempts to restore native viewing. Backend switches can require the reconnect described above.

## Source layout

| Path | Purpose |
|---|---|
| `native/camera.py` | Native macOS USB transport and frame acquisition |
| `native/extract_recipe.py` | Extract the local startup recipe from the original trace |
| `native/trace.py`, `native/usb_trace.h` | Development USB trace reader and recorder |
| `gui/app.py`, `gui/static/` | Local Flask server and browser interface |
| `gui/native_bridge.py` | Native acquisition worker used by the GUI |
| `gui/analysis.py` | Spot centroids, reference matching and Zernike fitting |
| `gui/bridge.py`, `gui/sdk_live.py` | Earlier optional Linux/QEMU backend |
| `benchmark.py` | Hardware performance comparison |
| `usb_configuration_fix.c` | USB recovery shim used only by the VM backend |

Future work includes reliable warm restarts, native exposure/gain control, diagnostic test patterns, calibrated optical validation, and small-angle tip/tilt measurement and removal.
