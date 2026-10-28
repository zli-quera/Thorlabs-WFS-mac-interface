"""Owns a local vendor-driver helper and publishes its live-frame directory."""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time


class CameraBridge:
    def __init__(self, root):
        self.root = Path(root)
        self.guest_script = "sdk_live.py"
        self.guest_output = "/mnt/host/runtime/live"
        (self.root / "diagnostics").mkdir(parents=True, exist_ok=True)
        self.live = self.root / "runtime" / "live"
        self.live.mkdir(parents=True, exist_ok=True)
        self.process = None
        self.thread = None
        self.stopping = threading.Event()
        self.message = "Camera stopped"
        self.stage = "stopped"
        self.socket_dir = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopping.clear()
        for name in ("stop", "frame.bin", "status.json"):
            (self.live / name).unlink(missing_ok=True)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def controls(self, exposure_ms, gain):
        temporary = self.live / "controls.tmp"
        temporary.write_text(json.dumps({"exposure_ms": exposure_ms, "gain": gain}))
        os.replace(temporary, self.live / "controls.json")

    def _monitor(self, command):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(.5)
            connection.connect(str(self.socket_dir / "monitor"))
            connection.recv(65536)
            connection.sendall(command.encode() + b"\n")
            try:
                connection.recv(65536)
            except socket.timeout:
                pass

    def _refresh(self):
        self._monitor("device_del wfs")
        time.sleep(.5)
        self._monitor("device_add usb-host,id=wfs,bus=xhci.0,vendorid=0x1409,guest-reset=off,pipeline=off,loglevel=0")

    def _run(self):
        try:
            self.stage, self.message = "starting", "Starting camera"
            runtime = self.root / "runtime"
            disk = runtime / "driver.qcow2"
            if not disk.exists():
                raise RuntimeError("The local camera driver runtime is missing.")
            library = runtime / "usb_recovery.dylib"
            source = self.root / "usb_configuration_fix.c"
            if not library.exists() or source.stat().st_mtime > library.stat().st_mtime:
                subprocess.run(["clang", "-dynamiclib", "-I/opt/homebrew/include/libusb-1.0",
                                "-L/opt/homebrew/lib", "-lusb-1.0", "-o", str(library), str(source)], check=True)
            with tempfile.TemporaryDirectory(prefix="wfs-") as directory:
                self.socket_dir = Path(directory)
                environment = dict(os.environ, DYLD_INSERT_LIBRARIES=str(library))
                if (self.root / "native" / "trace_enabled").exists():
                    environment["WFS_NATIVE_TRACE"] = str(getattr(self, "trace_path", self.root / "native" / "usb_trace.bin"))
                command = [shutil.which("qemu-system-x86_64") or "/opt/homebrew/bin/qemu-system-x86_64",
                           "-machine", "q35", "-cpu", "max", "-accel", "tcg", "-m", "1536", "-smp", "2",
                           "-drive", f"file={disk},format=qcow2,if=virtio", "-nic", "user,model=virtio-net-pci",
                           "-virtfs", f"local,path={self.root},mount_tag=hostshare,security_model=none,id=hostshare",
                           "-device", "qemu-xhci,id=xhci", "-device",
                           "usb-host,id=wfs,bus=xhci.0,vendorid=0x1409,guest-reset=off,pipeline=off,loglevel=0",
                           "-display", "none", "-serial", f"unix:{directory}/serial,server,nowait",
                           "-monitor", f"unix:{directory}/monitor,server,nowait"]
                with (self.root / "diagnostics" / "gui_driver.log").open("wb") as log:
                    self.process = subprocess.Popen(command, env=environment, stdout=log, stderr=log)
                    with socket.socket(socket.AF_UNIX) as serial:
                        serial.settimeout(.5)
                        for _ in range(100):
                            if self.process.poll() is not None:
                                raise RuntimeError("Camera driver helper could not start; see driver log.")
                            try:
                                serial.connect(str(self.socket_dir / "serial"))
                                break
                            except (FileNotFoundError, ConnectionRefusedError):
                                time.sleep(.1)
                        else:
                            raise RuntimeError("Camera helper did not open its console.")
                        serial.sendall(b"\n")
                        stage, buffer, began, refreshes = 0, b"", 0., 0
                        serial_log = (self.root / "diagnostics" / "gui_serial.log").open("wb")
                        try:
                            while not self.stopping.is_set() and self.process.poll() is None:
                                try:
                                    data = serial.recv(65536)
                                    if not data:
                                        break
                                    serial_log.write(data)
                                    serial_log.flush()
                                    buffer = (buffer + data)[-30000:]
                                except socket.timeout:
                                    pass
                                if stage == 0 and b"localhost login:" in buffer:
                                    serial.sendall(b"root\n")
                                    buffer, stage = b"", 1
                                elif stage == 1 and re.search(rb"root@[^\r\n]*#", buffer):
                                    serial.sendall(("mkdir -p /mnt/host; mount -t 9p -o trans=virtio,version=9p2000.L hostshare /mnt/host; python3 -u /mnt/host/gui/" + self.guest_script + " " + self.guest_output + "\n").encode())
                                    buffer, stage, began = b"", 2, time.monotonic()
                                    self.stage, self.message = "connecting", "Connecting to sensor"
                                if stage == 2:
                                    frame = self.live / "frame.bin"
                                    if frame.exists() and time.time() - frame.stat().st_mtime < 3:
                                        self.stage, self.message = "streaming", "Camera online"
                                    elif time.monotonic() - began > 12 + 18*refreshes and refreshes < 3:
                                        self.message = "Finishing camera initialization"
                                        self._refresh()
                                        refreshes += 1
                            (self.live / "stop").touch()
                            # Give the capture loop time to release its image buffer and sensor.
                            time.sleep(1)
                            try:
                                serial.sendall(b"\npoweroff\n")
                            except OSError:
                                pass
                            until = time.monotonic() + 20
                            while self.process.poll() is None and time.monotonic() < until:
                                try:
                                    serial.recv(65536)
                                except (OSError, socket.timeout):
                                    pass
                        finally:
                            serial_log.close()
        except Exception as error:
            self.stage, self.message = "error", str(error)
        finally:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            if self.stage != "error":
                self.stage, self.message = "stopped", "Camera stopped"

    def stop(self):
        self.stopping.set()
        (self.live / "stop").touch()

    def read(self):
        path = self.live / "frame.bin"
        try:
            with path.open("rb") as stream:
                metadata = json.loads(stream.readline())
                pixels = stream.read()
            if time.time() - metadata["time"] > 3:
                return None
            return metadata, pixels
        except (OSError, ValueError, KeyError):
            return None
