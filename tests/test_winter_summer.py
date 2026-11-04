import sys
from pathlib import Path
import unittest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from compare_winter_summer import common_ids, paired


class WinterSummerTests(unittest.TestCase):
    def test_common_ids_requires_both_observation_months(self):
        d = pd.DataFrame({'month': ['2025-01', '2025-01', '2025-07', '2025-06'],
                          'station_id': ['a', 'b', 'b', 'a']})
        self.assertEqual(common_ids(d, 'station_id'), {'b'})

    def test_paired_threshold_applies_to_each_month_without_zero_fill(self):
        d = pd.DataFrame({'grid_id': ['a', 'a', 'b', 'b', 'c'],
                          'month': ['2025-01', '2025-07', '2025-01', '2025-07', '2025-01'],
                          'guns': [5, 5, 4, 8, 9], 'orders': [5]*5,
                          'utilization': [.1, .2, .3, .4, .5]})
        p = paired(d, 'utilization', 'guns')
        self.assertEqual(p.index.tolist(), ['a'])
        self.assertAlmostEqual(p.loc['a', '2025-07'] - p.loc['a', '2025-01'], .1)
