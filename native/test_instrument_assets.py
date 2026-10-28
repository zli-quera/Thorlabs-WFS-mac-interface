import gzip,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import instrument_assets as assets
import test_factory_memory as fixtures
import doctor

class AssetTests(unittest.TestCase):
    def create_assets(self,root):
        recipe=dict(serial='4110057336',usb_id='1409:3370',boot=['00'],initialize=['00'],capture=['00'],initialize_status=[0],end_capture='00')
        files={'native/recipe.json.gz':gzip.compress(json.dumps(recipe).encode()),
               'runtime/factory_memory.bin':fixtures.FactoryRecordTests().sample()}
        for name,data in files.items():p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    def test_round_trip_contains_only_instrument_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'source';self.create_assets(root)
            bundle=Path(directory)/'assets.instrument.zip';manifest=assets.export_assets(bundle,root)
            target=Path(directory)/'target';assets.import_assets(bundle,target)
            for name in assets.FILES:self.assertEqual((root/name).read_bytes(),(target/name).read_bytes())
            with zipfile.ZipFile(bundle) as z:self.assertEqual(set(z.namelist()),{'manifest.json',*assets.FILES})
            self.assertEqual(manifest['camera_serial'],'4110057336')
    def test_extra_path_and_corruption_are_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'source';self.create_assets(root)
            good=Path(directory)/'good.zip';assets.export_assets(good,root)
            with zipfile.ZipFile(good) as z:files={name:z.read(name) for name in z.namelist()}
            for name,modified in [('path',{**files,'../escape':b'x'}),('corrupt',{**files,'runtime/factory_memory.bin':b'corrupt'})]:
                bad=Path(directory)/(name+'.zip')
                with zipfile.ZipFile(bad,'w') as z:
                    for member,data in modified.items():z.writestr(member,data)
                target=Path(directory)/name
                with self.assertRaises(ValueError):assets.import_assets(bad,target)
                self.assertFalse(target.exists())
    def test_offline_doctor_never_loads_usb(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.create_assets(root)
            with patch.object(doctor,'ROOT',root),patch.object(doctor,'load_libusb') as load:
                result=doctor.report(offline=True)
                load.assert_not_called();self.assertTrue(result['ready'])

if __name__=='__main__':unittest.main()
