# Thorlabs wavefront sensor interface

Direct USB acquisition, live camera display, and wavefront reconstruction for Thorlabs wavefront sensors.

The software reads the sensor's model, serial number, microlens-array information, and stored optical calibration automatically. Factory reference coordinates and the stored focal length are used for reconstruction; users do not need to enter the sensor model or calibration parameters manually.

## What works

- Native volatile firmware loading with RAM readback verification, FPGA configuration, and checked command acknowledgements.
- Native access to the stored factory identity/MLA record, with checksum validation. [Factory-memory details](docs/factory_memory.md). The viewer constructs the reference grid automatically from its offsets and geometric corrections.
- Live raw camera preview, currently displayed at about two updates per second.
- Detection of Shack–Hartmann spots above an adjustable intensity/noise threshold.
- Relative wavefront reconstruction by fitting 14 Zernike gradient modes to spot displacements from a measured reference.
- Fitted tip/tilt angles in mrad in the viewer, with optional removal only when both absolute components are strictly below the adjustable cutoff; piston is removed.
- A 14 FPS test mode with five optical alignment sliders and factory-offset-corrected simulated frames.
- Offline PNG/PGM analysis, measured and displayed Zernike coefficients, and RMS before/after removal.
- Wavefront and metrics hidden on dark, stale, saturated, diagnostic, or otherwise invalid data.

## Important limits

- Native exposure is adjustable from **0.04–150 ms requested**, quantized to sensor timing; the viewer reports the applied exposure. Digital gain is adjustable from **0–100% (1×–4×)**. These controls are enabled during native streaming.
- Switching backends or reopening the camera can leave incomplete FPGA configuration and require a physical USB reconnect. Startup detects this condition; automatic recovery remains unfinished.
- A fresh native start took about 14 seconds in the measured run. This is not yet an optimized streaming driver.
- The native backend is restricted to the tested instrument serial. Support for other instruments requires protocol and calibration validation.
- Optical wavefront accuracy under calibrated illumination has not yet been validated. Synthetic defocus recovery and recorded USB frame decoding have been tested.
- The per-axis small-tilt cutoff defaults to 500 µrad (0.5 mrad) as an editable software setting, not an instrument specification. Angles refer to the fitted tilt modes relative to the reference.

## Local firmware dependency

**A source-only checkout cannot acquire images by itself.** Native capture also needs `native/recipe.json.gz`, which contains this instrument's recorded startup commands and vendor firmware payloads. The working local copy already has it; it is deliberately excluded from Git, along with the original USB traces, captured images, and calibration data.

`native/extract_recipe.py` can regenerate that recipe from the original local `native/usb_trace_initial.bin`. Its packet ranges are specific to that recording; it is not a general trace importer. Keep these local files available when moving this working setup to another computer.

## Windows test branch

This branch adds native Windows x64 USB support, pending a sensor test on Windows. See [Windows setup and testing](docs/windows_setup.md) for the direct Python commands, WinUSB/DLL setup and local instrument-asset transfer. No new virtual environment or shell launcher is required. macOS hardware remains the validated reference.

## Requirements and installation

- Python 3.12.
- Flask, NumPy, SciPy, and Pillow. Tested versions are listed in `requirements.txt`.
- libusb for hardware acquisition. On macOS it can be installed with `brew install libusb`.
- The local startup recipe described above for hardware acquisition.

Using your preferred Python interpreter, install the Python dependencies from the repository root:

```sh
python -m pip install -r requirements.txt
```

The firmware recipe described above must also be present. The native backend needs direct access to the USB device; a restricted execution environment may prevent enumeration. Only one process should own the sensor at a time.

## Run

```sh
python gui/app.py
```

Open **http://127.0.0.1:8864**. The server binds only to the local computer.

Run commands from the repository root with the Python interpreter you chose for installation.

If startup reports incomplete FPGA configuration, unplug and reconnect the sensor, then press **Start**. Avoid running the standalone hardware probe while the GUI camera is active.

Factory matching uses unique nearest-lenslet assignments without a displacement cutoff. Large displacement, low matching coverage, or large fit residual produces an on-screen reliability warning while processing continues. The factory reference remains unchanged. Absolute tilt can wrap by a lenslet pitch; warnings cannot identify every such ambiguity from one periodic spot image. Valid signal, enough distinct lenslets, and a solvable spatial fit are still required.

## Exposure, gain and saturation

During native streaming, edit **Exposure (ms)** and **Digital gain (%)**. The capture worker applies changes between completed frames with checked USB acknowledgements; the HTTP thread never sends camera commands concurrently with acquisition. Requested settings stay in the inputs, while the camera caption and frame metadata report applied exposure and gain. These are volatile settings and do not write factory memory.

Exposure requests are quantized to the sensor's supported timing; the camera caption reports the applied value. The existing frame-blanking configuration is preserved, so acquisition rate may vary with exposure. Digital gain scales pixel values and does not recover clipped signal.

The preview marks pixels at or above 254 DN in red. The overlay pools the saturation mask before downsampling, so individual clipped pixels remain visible. Raw pixels used for analysis and saved captures remain monochrome and unchanged. Hardware exposure/gain controls are disabled for saved images and test-mode frames.

## Wavefront analysis

1. Start the native camera once to read its factory record, or use an already cached record. The viewer uses the factory reference automatically.
2. Adjust the spot threshold and minimum usable spot count. A known flat reference image is optional if you want a measured relative reference instead.
3. Factory identity, pixel pitch, lenslet pitch and effective focal length are read automatically during native initialization and cached under `runtime/`. The viewer uses a valid cached factory record for offline images from that same sensor; no manually entered model or focal length is required.
4. For an optional measured reference, illuminate with a known flat wavefront and press **Set flat reference**. Otherwise retain the automatic factory reference.
5. Measure subsequent changes relative to that reference. Enable **Remove small tip / tilt** and set the per-axis cutoff in µrad. Tilt above the cutoff stays in the displayed wavefront; measured coefficients remain unchanged.

The readout reports fitted X/Y tilt and total angular magnitude, with X to the right and Y downward in image coordinates. For normalized first-order Zernike modes `Z = 2x, 2y`, physical OPD tilt slopes are `2 * coefficient_um / pupil_radius_um`. Angles are `atan(slope)` in µrad; total tilt uses `atan(hypot(slope_x, slope_y))`. Removal requires `abs(X) < cutoff` **and** `abs(Y) < cutoff`; equality does not qualify. The default is 500 µrad per component. The vector magnitude is informational and does not control removal. The viewer displays angles in mrad; the API and CLI retain µrad.

For offline work without opening USB hardware:

```sh
python gui/app.py --offline
```

Use **Analyze saved image** to load a measurement PNG/PGM. With a valid cached factory record, reconstruction starts automatically. Use images from the same instrument that supplied the cached record. Alternatively, load a known flat image, set a measured reference, then load the measurement. Raw images must be 8-bit monochrome and use the calibration for the same sensor. A saved intensity image alone does not establish an absolute wavefront.

A command-line analyzer is also available:

```sh
python analyze_image.py measurement.png --factory-memory runtime/factory_memory.bin \
    --tilt-limit-urad 500 --output result.json
```

The factory-memory option supplies reference coordinates and the stored focal length. For a measured reference instead, use `--reference flat.png --focal-mm VALUE`. Without either reference source, the CLI reports signal quality only. Use `--keep-tilt` to retain tilt regardless of magnitude.

The local slope model is `slope = spot_displacement / lenslet_focal_length`, using consistent physical units. Zernike derivatives are fitted to these slopes. Output is optical path difference in micrometres over the measured pupil coverage. Factory reference positions are calculated from checksum-validated memory parameters. If no valid factory record is available, supply a measured flat reference and focal length explicitly. A reference measured under an aberrated beam defines that aberration as the relative zero.

The **Wavefront unit** dropdown switches the map scale, RMS/PV, and measured/displayed Zernike coefficients between micrometres and waves. Waves is the default, with an editable wavelength of **700 nm**. Conversion is `waves = OPD_um × 1000 / wavelength_nm`; these are unwrapped optical path differences in cycles. A positive wavelength is required. Unit changes affect display only; tilt angles stay in mrad, the removal cutoff stays in µrad, and API/CLI results remain in physical units.

## Test mode

Start `python gui/app.py --offline`, open the viewer, and enable **Test mode · 14 FPS**. A validated local `runtime/factory_memory.bin` is required; run the native reader once if it is missing. USB capture stops when test mode starts. Disable test mode to stop simulation; **Start** explicitly returns to hardware acquisition.

Five sliders and numeric inputs control fiber X/Y (±500 µm), fiber Z (±5 mm), and KM100 tip/tilt (±30 mrad). **Reset alignment** zeros all five. Simulated 2048×2048 mono8 frames include the actual factory offsets and geometric corrections. They pass through the same threshold gate, centroid detector, factory matching, and 14-mode Zernike fit as real frames; analytical slopes are never supplied to the fitter. The rate readout reports actual analysis throughput against the 14 FPS target. At zero alignment, offsets cancel to pixel quantization precision.

The default removal rule applies to real, saved, and simulated data: both fitted components must be strictly below 0.5 mrad. Above that limit, the option is disabled and tilt stays visible. Below it, toggle **Remove small tip / tilt** to compare the full and corrected wavefront. The expanded coefficient table lists normalized real Zernike `(n,m)` modes with measured and displayed OPD coefficients in the selected unit; the measured values remain available after removal.

The optical model is an ideal, aberration-free 125 mm collimator with the fiber at its front focal point and a WFS 100 mm beyond the lens. It traces rays in the rotated lens coordinates and propagates them to the WFS, then uses the stored MLA focal length to render spot displacement. The beam radius is 1.75 mm; spots have 1.7-pixel Gaussian sigma and 8-bit quantization, without random noise. Positive fiber Z increases the source-to-lens distance. Tip rotates about camera X and tilt about camera Y, about the lens center. X points right and Y down.

**This treats KM100 as the lens holder.** A centered lens rotation does not produce the `2 × angle` steering of a mirror. Its leading effects here are weak coma/astigmatism and higher-order steering; lateral fiber translation primarily controls beam tilt, and Z primarily controls defocus. This ideal model does not include the AC254 glass/surface prescription, wavelength dependence, diffraction, an offset mechanical pivot, or real aberration/noise performance. It is for testing alignment/reconstruction behavior, not predicting the exact achromat's aberrations. Nominal focus is defined by the effective focal plane; no unverified physical working distance is assumed.

## Tests

```sh
python -m unittest discover -s gui -p 'test_*.py'
python -m unittest discover -s native -p 'test_*.py'
```

The GUI suites check synthetic defocus/mixed-aberration recovery, tilt units and cutoff behavior, signal/calibration gates, and offline input validation without hardware. The native suites check factory checksums/field decoding and transport framing. Tests requiring local instrument traces or startup assets skip when those files are unavailable.

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

## Windows portability

The native USB transport is isolated in `native/usb_transport.py`, with platform library loading in `native/libusb_loader.py`. Windows x64 uses libusb/WinUSB; startup, re-enumeration and hardware behavior still require Windows validation. See [Windows setup](docs/windows_setup.md) and the [portability plan](docs/windows_port.md).

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
| `gui/simulation.py` | Ideal collimator ray tracing and factory-offset camera simulation |
| `gui/analysis.py` | Spot centroids, reference matching and Zernike fitting |
| `gui/bridge.py`, `gui/sdk_live.py` | Earlier optional Linux/QEMU backend |
| `benchmark.py` | Hardware performance comparison |
| `usb_configuration_fix.c` | USB recovery shim used only by the VM backend |

Future work includes reliable warm restarts, diagnostic test patterns, calibrated optical validation, and further optical validation of tilt measurement and removal.
