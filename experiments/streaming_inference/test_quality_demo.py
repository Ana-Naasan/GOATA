import copy
import unittest
import quality_demo


def report():
    frames=[dict(frame_id=i,pts_ns=str(i*100),original_pts=str(i),original_time_base='1/10000000') for i in range(4)]
    return dict(status='complete',fixture=dict(original_identity={'sha256':'a'*64,'byte_size':99},
        source_frame_count=4,original_origin_seconds='0',rate='30',chunks=[{'frames':frames}]))


class QualityDemoTests(unittest.TestCase):
    def test_same_original_and_source_clock_required_across_resolutions(self):
        a=report(); b=copy.deepcopy(a)
        self.assertEqual(len(quality_demo.common_source([a,b])),4)
        b['fixture']['chunks'][0]['frames'][2]['pts_ns']='201'
        with self.assertRaises(ValueError):quality_demo.common_source([a,b])

    def test_failed_run_cannot_be_presented_as_successful_demo(self):
        a=report(); b=copy.deepcopy(a);b['status']='failed'
        with self.assertRaises(ValueError):quality_demo.common_source([a,b])

    def test_different_original_rejected(self):
        a=report();b=copy.deepcopy(a);b['fixture']['original_identity']['sha256']='b'*64
        with self.assertRaises(ValueError):quality_demo.common_source([a,b])


if __name__=='__main__':unittest.main()
