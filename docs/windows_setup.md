# Windows x64 test instructions

Branch: `codex/windows-support`. Windows USB support is implemented but **has not yet been tested with this sensor on a Windows machine**. The current macOS capture can keep running while these files are prepared. No VM or vendor host SDK is required by this branch.

## 1. Get the branch and install Python dependencies

Use your existing x64 Python 3.12 installation/environment. No new virtual environment or activation script is required. If `python` is not your intended global environment, substitute its full executable path in each command.

```powershell
git clone --branch codex/windows-support git@github.com:zli-quera/Thorlabs-WFS-mac-interface.git
cd Thorlabs-WFS-mac-interface
python -m pip install -r requirements.txt
```

For an existing checkout, use `git fetch origin` then `git switch codex/windows-support` and `git pull --ff-only`.

## 2. Transfer the instrument's local assets

The GitHub source excludes the startup recipe/firmware and factory cache. Copy `runtime/wfs4110057336.instrument.zip` from the working Mac to the Windows machine, for example into Downloads. This bundle was generated for camera serial **4110057336**, WFS serial **M01308502**. Then:

```powershell
python native/instrument_assets.py import "$HOME\Downloads\wfs4110057336.instrument.zip"
```

The importer validates checksums and factory records and writes only `native/recipe.json.gz` and `runtime/factory_memory.bin`. Importing intentionally replaces those two local instrument assets. It does not load firmware into the sensor or change its driver. Keep the bundle local; it is ignored by Git. Hashes detect transfer corruption, not the trustworthiness of an unknown bundle.

To regenerate the bundle on the Mac from the repo root:

```sh
~/envs/distortion/bin/python native/instrument_assets.py export runtime/wfs4110057336.instrument.zip
```

## 3. Check software without the sensor

```powershell
python native/doctor.py --offline
python -m unittest discover -s native -p "test_*.py"
python -m unittest discover -s gui -p "test_*.py"
python gui/app.py --offline
```

Open http://127.0.0.1:8864 and enable **Test mode**. Check the five sliders, factory-offset cancellation, waves/µm switch, wavelength, Zernike table, RMS/PV and tilt-removal cutoff. None of these steps requires a USB DLL or a sensor driver. Tests using the original untracked USB trace skip when that fixture is absent. Close this viewer with Ctrl+C before starting live capture.

## 4. Install the Windows USB runtime

Download the x64 Windows binary of `libusb-1.0.dll` from the [official libusb releases](https://github.com/libusb/libusb/releases). Choose the MS64/x64 build, not Win32 or ARM64. Put it at:

```text
native/vendor/libusb-1.0.dll
```

Alternatively set an absolute path in the same PowerShell session:

```powershell
$env:WFS_LIBUSB_PATH = "C:\path\to\libusb-1.0.dll"
```

The loader uses the explicit override or the qualified repo-local path; it does not search arbitrary DLLs in the current directory. Python and DLL architecture must match. Windows x64 is the initial target; Windows ARM64 and 32-bit Python are not supported by this branch.

For USB access, use **WinUSB** for the sensor. The [libusb Windows documentation](https://github.com/libusb/libusb/wiki/Windows) recommends WinUSB and documents its configuration/reset limitations. If the sensor currently uses a vendor driver, record that binding before changing it. [Zadig](https://zadig.akeo.ie/) can install WinUSB; select only the sensor with **VID 1409 / PID 3370**, verify its identity, and close other camera applications. This is a manual driver change on the Windows machine, not something this app performs. The vendor application may require restoring its original driver later.

Check both initial boot and runtime enumeration if firmware startup changes the device instance. This branch preserves the tested device ID and serial restriction. It avoids re-setting configuration 1 when already active and does not issue the macOS-specific U1/U2 workaround or a USB reset on Windows.

## 5. Check and run live capture

```powershell
python native/doctor.py --usb --output diagnostics/windows-host.json
python gui/app.py
```

The doctor lists USB descriptors without opening or claiming the sensor. Finding a device does not prove WinUSB access; the live startup test verifies that next. In the viewer check:

1. The status identifies native Windows USB and the frame counter advances.
2. The reported model, serial, array and focal length match the factory record.
3. Exposure and digital gain can be changed. Applied exposure is quantized (0.29 ms requested gives 0.285735 ms in this configuration). Saturated pixels appear red.
4. Wavefront fitting responds to alignment. Large displacement is advisory and does not hide the fit. Both tilt components must be below 0.5 mrad for optional removal.
5. The selected OPD units, Zernike coefficients, RMS/PV before and after removal, and camera/analysis FPS update.
6. Stop/start, a cold USB reconnect and a warm restart are tested separately. Reconnect physically if the known incomplete-FPGA state occurs; Windows does not gain a new automatic reset/recovery path in this branch.

The viewer currently throttles real acquisition to about two frames per second on all platforms; its FPS readout measures actual delivery, not the earlier unthrottled acquisition benchmark. Windows throughput has not been measured.

If startup fails, save the doctor JSON and `diagnostics/native_protocol.jsonl`, plus the displayed error. `NOT_SUPPORTED` or `ACCESS` at open commonly calls for checking driver binding and other applications. Wrong-architecture/missing-DLL failures are reported before USB capture starts. Keep the instrument bundle and raw captures out of Git.
