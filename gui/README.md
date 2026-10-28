Open http://127.0.0.1:8864 while the viewer is running. To launch again, double-click ../open_viewer.command.

The camera now uses the native macOS backend in ../native/camera.py. No Linux helper is launched. It displays raw 2048×2048 mono frames, downsampled to 1024×1024 in the browser, at about two updates per second. The first native backend fixes exposure at nominal 10 ms and gain at 0%; those controls are disabled pending native register verification. A fresh camera start takes approximately 15 seconds. The browser needs no camera permission.

Wavefront: relative optical path difference in µm, fitted to 14 Zernike modes from reference spot displacements. Illuminate with a known flat wavefront, set the flat reference, and enter the mounted microlens focal length. No factory lenslet calibration is assumed. The fit removes piston and optionally tip/tilt, and displays only within measured pupil coverage.

The adjustable threshold is spot intensity above background in 8-bit DN, with an additional noise floor. Minimum count, saturation, unique reference matching, coverage and fit residual gates must also pass. Dark, stale, diagnostic or invalid frames clear the wavefront and its metrics. Synthetic defocus recovery is tested; illuminated calibrated optical measurements remain to be validated.
