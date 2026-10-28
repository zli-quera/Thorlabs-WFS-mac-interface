# Factory memory access

The sensor's 512-byte protected memory region has now been read through both the reference SDK and the native macOS path. The native path preserves the response to the protected-memory query already performed by its normal initialization sequence; it does not write EEPROM. Local copies are `runtime/factory_memory.bin` and `runtime/factory_calibration.json`, excluded from Git.

The record layout was checked against the official Thorlabs WFS 6.3 driver, particularly `WFS_ReadEEPROM2`, the MLA record decoder, and the public `WFS_GetMlaData` parameter definitions. Model and array names use byte values shifted by -32. Each 64-byte record ends with a 16-bit little-endian checksum: 1234 plus the signed-byte sum of the first 62 bytes, modulo 65536.

The first record identifies the Thorlabs model and serial. Subsequent records describe the calibrated arrays. Optical values include camera pixel pitch and lenslet pitch (float64), spot offsets, focal length and grid-correction fields (float32). The decoder converts stored focal length in µm to mm. The pixel pitch, lenslet pitch and focal length ranges are checked against the driver's supported ranges. The remaining fields are now decoded as signed rotation (millidegrees), pitch correction (ppm), and four signed higher-order coefficients (ppb). `gui/factory_reference.py` reproduces the vendor calculation's order: 0°/45° anisotropy, pitch scaling, rotation, trefoil/coma polynomial corrections, then the stored spot offsets. Offsets are in camera pixels relative to the full-frame center. The cached record is used automatically by the GUI and can be passed to the CLI with `--factory-memory`.

This implementation currently supports full 2048×2048 WFS40 frames only. It generates reference coordinates entirely from factory parameters; it never fits grid position or pitch to the measured spots. It then restricts the reference pupil to illuminated lenslets with unique matches within 0.4 nominal lenslet pitch. A single calibrated array is selected automatically; multiple stored arrays require explicit selection of the physically installed MLA. A measured flat reference, if set, overrides the factory grid.

For the measured instrument, the offsets are X = -12.1410522461 px and Y = -13.4994506836 px. Its stored effective focal length is 4.973787109375 mm, rather than the typical 5.2 mm catalog value. Grid corrections are -20 ppm at 0° and -20 ppm at 45°, rotation 0 mdeg, pitch correction -140 ppm, trefoil Y/X = -15/0 ppb, and coma Y/X = -25/0 ppb.

For this instrument, the identity and installed-array checksums validate, and the protected-memory dump from native macOS is byte-for-byte identical to the independent SDK read. Its stored focal length differs from the typical catalog value; the viewer was updated to the stored value in its running configuration. The nominal model default remains available when no factory profile has been loaded.

Decode a local dump without camera access:

```sh
python native/read_factory.py
python native/factory_memory.py runtime/factory_memory.bin --output runtime/factory_calibration.json
python -m unittest discover -s native -p 'test_factory_memory.py'
```

`gui/read_memory_sdk.py` is an optional reference-driver diagnostic for querying the sizes and reading the standard, extended and protected memory regions. It issues only persistent-memory GET_SIZE/READ commands; no persistent-memory WRITE commands are implemented in it.
