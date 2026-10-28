import struct
import unittest
from factory_memory import decode


def seal(record):
    checksum=(1234+sum(x if x<128 else x-256 for x in record[:62]))&65535
    struct.pack_into('<H',record,62,checksum)
    return record


def encoded(value):
    return bytes((b-32)&255 for b in value.encode().ljust(16,b'\0'))


class FactoryRecordTests(unittest.TestCase):
    def sample(self):
        header=bytearray(64);header[:16]=encoded('WFS40-7AR');header[16:32]=encoded('TEST00001')
        mla=bytearray(64);mla[:16]=encoded('MLA150M-7AR')
        struct.pack_into('<dd5f',mla,16,5.5,150.,-12.,-13.,4975.,-20.,-20.)
        struct.pack_into('<hhbbbb',mla,52,10,-140,-15,0,-25,0)
        return bytes(seal(header)+seal(mla)+bytearray(384))
    def test_decode_and_units(self):
        result=decode(self.sample())
        self.assertEqual(result['model'],'WFS40-7AR')
        self.assertEqual(result['thorlabs_serial'],'TEST00001')
        mla=result['arrays'][0]
        self.assertEqual(mla['pixel_um'],5.5)
        self.assertEqual(mla['lenslet_pitch_um'],150)
        self.assertEqual(mla['focal_mm'],4.975)
        self.assertEqual(mla['grid_rotation_mdeg'],10)
        self.assertEqual(mla['grid_pitch_ppm'],-140)
        self.assertEqual(mla['trefoil_y_ppb'],-15)
        self.assertEqual(mla['coma_y_ppb'],-25)
        self.assertTrue(result['reference_mapping_implemented'])
    def test_corrupt_and_truncated_records_rejected(self):
        raw=bytearray(self.sample());raw[100]^=1
        with self.assertRaisesRegex(ValueError,'checksum'):decode(raw)
        with self.assertRaisesRegex(ValueError,'512'):decode(raw[:-1])

if __name__=='__main__':unittest.main()
