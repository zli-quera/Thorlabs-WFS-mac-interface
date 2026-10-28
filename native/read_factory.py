"""Read and validate this instrument's factory EEPROM over native libusb USB.
Stop the GUI's live camera first. No persistent-memory writes are issued.
"""
import json
from camera import Camera

if __name__=='__main__':
    camera=Camera()
    try:
        camera.initialize()
        if camera.factory_calibration is None:
            raise RuntimeError('No validated factory record was returned')
        print(json.dumps(camera.factory_calibration,indent=2))
    finally:camera.close()
