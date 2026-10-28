# Native macOS wavefront sensor viewer

A native macOS interface for a Thorlabs wavefront sensor containing an IDS UI337xCP-M camera. It provides direct USB acquisition through libusb/IOKit, a live camera preview, and relative wavefront analysis on an Apple Silicon Mac.

This is a working instrument-specific prototype, identified as **WFS40-7AR** with an MLA150-7AR array (150 µm lenslet pitch, typical effective focal length 5.2 mm), tested with USB ID `1409:3370`, serial `4110057336`, at 2048 × 2048 monochrome 8-bit resolution and 5.5 µm pixel pitch. Support for additional instruments requires separate validation.

## What works

- Native volatile firmware loading with RAM readback verification, FPGA configuration, and checked command acknowledgements.
- Native access to the stored factory identity/MLA record, with checksum validation. [Factory-memory details](docs/factory_memory.md). The viewer constructs the reference grid automatically from its offsets and geometric corrections.
- Live raw camera preview, currently displayed at about two updates per second.
- Detection of Shack–Hartmann spots above an adjustable intensity/noise threshold.
- Relative wavefront reconstruction by fitting 14 Zernike gradient modes to spot displacements from a measured reference.
- Fitted tip/tilt angles in µrad, with optional removal only at or below an adjustable total-angle cutoff; piston is removed.
- Offline PNG/PGM analysis, measured and displayed Zernike coefficients, and RMS before/after removal.
- Wavefront and metrics hidden on dark, stale, saturated, diagnostic, or otherwise invalid data.

## Important limits

- Native exposure is currently fixed at nominal **10 ms**, with **0% gain**. Those GUI controls are disabled until their native commands are verified.
- Switching backends or reopening the camera can leave incomplete FPGA configuration and require a physical USB reconnect. Startup detects this condition; automatic recovery remains unfinished.
- A fresh native start took about 14 seconds in the measured run. This is not yet an optimized streaming driver.
- The native backend is restricted to the tested instrument serial. Support for other instruments requires protocol and calibration validation.
- Optical wavefront accuracy under calibrated illumination has not yet been validated. Synthetic defocus recovery and recorded USB frame decoding have been tested.
- The small-tilt cutoff defaults to 100 µrad as an editable software setting, not an instrument specification. Angles refer to the fitted tilt modes relative to the reference.

## Local firmware dependency

**A source-only checkout cannot acquire images by itself.** Native capture also needs `native/recipe.json.gz`, which contains this instrument's recorded startup commands and vendor firmware payloads. The working local copy already has it; it is deliberately excluded from Git, along with the original USB traces, captured images, and calibration data.

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

1. Start the native camera once to read its factory record, or use an already cached record. The viewer uses the factory reference automatically.
2. Adjust the spot threshold and minimum usable spot count. A known flat reference image is optional if you want a measured relative reference instead.
3. Factory identity, pixel pitch, lenslet pitch and effective focal length are read automatically during native initialization and cached under `runtime/`. The viewer uses a valid cached factory record for offline images from that same sensor; no manually entered model or focal length is required.
4. For an optional measured reference, illuminate with a known flat wavefront and press **Set flat reference**. Otherwise retain the automatic factory reference.
5. Measure subsequent changes relative to that reference. Enable **Remove small tip / tilt** and set the total-angle cutoff in µrad. Tilt above the cutoff stays in the displayed wavefront; measured coefficients remain unchanged.

The readout reports fitted X/Y tilt and total angular magnitude, with X to the right and Y downward in image coordinates. For normalized first-order Zernike modes `Z = 2x, 2y`, physical OPD tilt slopes are `2 * coefficient_um / pupil_radius_um`. Angles are `atan(slope)` in µrad; total tilt uses `atan(hypot(slope_x, slope_y))`. The cutoff applies to this total magnitude, inclusively.

For offline work without opening USB hardware:

```sh
python gui/app.py --offline
```

Use **Analyze saved image** to load a measurement PNG/PGM. With a valid cached factory record, reconstruction starts automatically. Use images from the same instrument that supplied the cached record. Alternatively, load a known flat image, set a measured reference, then load the measurement. Raw images must be 8-bit monochrome; the GUI uses this sensor’s 5.5 µm pixel size. A saved intensity image alone does not establish an absolute wavefront.

A command-line analyzer is also available:

```sh
python analyze_image.py measurement.png --factory-memory runtime/factory_memory.bin \
    --tilt-limit-urad 100 --output result.json
```

The factory-memory option supplies reference coordinates and the stored focal length. For a measured reference instead, use `--reference flat.png --focal-mm VALUE`. Without either reference source, the CLI reports signal quality only. Use `--keep-tilt` to retain tilt regardless of magnitude.

The local slope model is `slope = spot_displacement / lenslet_focal_length`, using consistent physical units. Zernike derivatives are fitted to these slopes. Output is optical path difference in micrometres over the measured pupil coverage. Factory reference positions are calculated from checksum-validated memory parameters. If no valid factory record is available, supply a measured flat reference and focal length explicitly. A reference measured under an aberrated beam defines that aberration as the relative zero.

## Tests

```sh
python -m unittest discover -s gui -p 'test_*.py'
python -m unittest discover -s native -p 'test_*.py'
```

The GUI suites check synthetic defocus/mixed-aberration recovery, tilt units and cutoff behavior, signal/calibration gates, and offline input validation without hardware. The native suites check factory checksums/field decoding and transport framing. Only the recorded-frame tests skip when the untracked instrument trace is unavailable.

For a standalone hardware capture, stop the GUI camera first:

```sh
python native/camera.py --frames 3
```

This writes raw PGM frames and metadata under the ignored `captures/native/` directory.

## Measured performance

The earlier acquisition backend used the vendor host SDK inside a Linux VM running under QEMU. The native macOS backend communicates directly with the sensor through libusb/IOKit and requires neither that VM nor the vendor host SDK at runtime. Both implementations are retained for comparison. The VM disk is excluded from Git.

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
| `native/read_factory.py`, `native/factory_memory.py` | Read and checksum-validate factory EEPROM records |
| `gui/factory_reference.py` | Build factory reference coordinates and select illuminated lenslets |
| `native/extract_recipe.py` | Extract the local startup recipe from the original trace |
| `native/trace.py`, `native/usb_trace.h` | Development USB trace reader and recorder |
| `gui/app.py`, `gui/static/` | Local Flask server and browser interface |
| `gui/native_bridge.py` | Native acquisition worker used by the GUI |
| `gui/analysis.py` | Spot centroids, reference matching and Zernike fitting |
| `gui/bridge.py`, `gui/sdk_live.py` | Earlier optional Linux/QEMU backend |
| `benchmark.py` | Hardware performance comparison |
| `usb_configuration_fix.c` | USB recovery shim used only by the VM backend |

Future work includes reliable warm restarts, native exposure/gain control, diagnostic test patterns, calibrated optical validation, and further optical validation of tilt measurement and removal.
