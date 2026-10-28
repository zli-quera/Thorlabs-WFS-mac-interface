import io
import unittest
import numpy as np
from PIL import Image
import app as viewer

class OfflineAPITests(unittest.TestCase):
    def setUp(self):
        self.client=viewer.app.test_client()
        viewer.simulator=None;viewer.offline_capture=None;viewer.reference=None;viewer.metadata={};viewer.frame=None
        self.original=dict(viewer.config)
    def tearDown(self):
        viewer.config.clear();viewer.config.update(self.original)
        viewer.simulator=None;viewer.offline_capture=None;viewer.reference=None;viewer.metadata={};viewer.frame=None
    def png(self,mode='L'):
        data=io.BytesIO();Image.new(mode,(32,32)).save(data,format='PNG');data.seek(0);return data
    def test_offline_input_and_reference_guard(self):
        reply=self.client.post('/api/image',data={'image':(self.png(),'dark.png')})
        self.assertEqual(reply.status_code,200)
        self.assertTrue(viewer.bridge.stopping.is_set())
        self.assertEqual(len(viewer.offline_capture[1]),1024)
        self.assertEqual(self.client.post('/api/reference').status_code,400)
        self.assertFalse(self.client.get('/api/state').json['analysis']['visible'])
        self.assertEqual(self.client.post('/api/image',data={'image':(self.png('RGB'),'color.png')}).status_code,400)
    def test_simulation_validation_and_source_selection(self):
        for bad in ({'x_um':501},{'tip_mrad':'nan'},{'z_mm':6}):
            self.assertEqual(self.client.post('/api/simulation',json=bad).status_code,400)
        if viewer.factory_profile:
            self.assertEqual(self.client.post('/api/simulation',json={'enabled':True,'reset':True}).status_code,200)
            self.assertIsNotNone(viewer.simulator)
            self.assertTrue(self.client.get('/api/state').json['simulation']['enabled'])
            self.assertEqual(self.client.post('/api/reference').status_code,400)
            self.assertEqual(self.client.post('/api/simulation',json={'enabled':False}).status_code,200)
            self.assertIsNone(viewer.simulator)

    def test_background_is_one_boolean_option(self):
        viewer.reference={'test':'old measured reference'}
        self.assertEqual(self.client.post('/api/config',json={'remove_background':True}).status_code,200)
        self.assertTrue(viewer.config['remove_background'])
        self.assertIsNone(viewer.reference)
        self.assertEqual(self.client.post('/api/config',json={'remove_background':False}).status_code,200)
        self.assertFalse(viewer.config['remove_background'])
        self.assertEqual(self.client.post('/api/config',json={'remove_background':'yes'}).status_code,400)

    def test_cutoff_validation_and_acceptance(self):
        for bad in (-1,'nan','inf'):
            self.assertEqual(self.client.post('/api/config',json={'tilt_limit_urad':bad}).status_code,400)
        self.assertEqual(self.client.post('/api/config',json={'tilt_limit_urad':0}).status_code,200)
        self.assertEqual(viewer.config['tilt_limit_urad'],0)

if __name__=='__main__':unittest.main()
