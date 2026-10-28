# Windows portability plan

Status: the `windows-support` branch implements the transport boundary, Windows x64 library loading, WinUSB setup differences, Python asset transfer and readiness checks. Unit tests run without Windows hardware; sensor operation on Windows still needs validation. Follow [Windows test instructions](windows_setup.md). The browser UI, NumPy/SciPy reconstruction, simulation, and saved-image analysis can remain shared.

## Recommended structure

Keep one camera protocol implementation and one analysis pipeline. Separate platform-specific USB loading and device access from command construction, factory-memory decoding, exposure/gain math, and frame parsing. The existing `USB` class in `native/camera.py` is the natural boundary.

1. Extract the USB transport and add a library loader. Use system discovery / an explicit override on macOS and a matching x64 `libusb-1.0.dll` on Windows. Remove the hardcoded Homebrew path from shared camera logic. Use a controlled DLL location and produce a clear architecture/dependency error.
2. Target Windows x64 first. Use libusb with WinUSB for control and bulk transfers. The libusb project recommends WinUSB and documents limits on reset, configuration selection and concurrent access; audit startup against those limits rather than assuming every macOS operation is portable. See the [official Windows backend documentation](https://github.com/libusb/libusb/wiki/Windows).
3. Validate driver binding in both firmware boot and runtime states, including re-enumeration. Check USB link-feature requests, interface claiming, endpoint recovery and concurrent acknowledgement/image reads. Keep the existing recipe's VID/PID and serial validation until another instrument has been independently checked.
4. Launch directly with `python gui/app.py` using the existing Python installation. No shell launcher or new virtual environment is needed. The page and analysis remain shared.
5. Make instrument assets explicit. A source checkout does not include `native/recipe.json.gz`, vendor firmware payloads, captures, or the local factory-memory cache. Supply authorized instrument assets locally and read calibration from that sensor on startup. Do not assume a fresh GitHub clone can cold-start the hardware by itself.

Changing the device's Windows driver binding can affect its availability to the vendor application. Record the original binding and document how to restore it; do not change it automatically as part of normal app startup.

## Validation order

- First run saved-image analysis and the synthetic test mode on Windows with a valid factory cache, without opening USB. Check file paths, imports, dependencies, GUI responsiveness and unit conversion.
- Run protocol, factory-memory and control-math tests on Windows. Provide local trace/recipe fixtures for tests that require them; the current untracked fixtures should remain untracked.
- With the sensor attached, validate cold startup, warm restart, disconnect/reconnect, identity and checksum reads, frame size/counters, and exposure/gain acknowledgements and pixel response.
- Check red saturation marking, high-tilt warnings, Zernike coefficients, RMS/PV before/after removal, and displayed FPS against the same recorded inputs used on macOS.
- Benchmark full-resolution acquisition and complete analysis separately. Do not infer Windows FPS from the current macOS measurements.

No Windows driver binding, package installation, or hardware change is performed by this plan.
