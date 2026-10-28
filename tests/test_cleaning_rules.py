import sys
from pathlib import Path
import unittest

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from clean_dataset import exclusion_rules


class CleaningRulesTests(unittest.TestCase):
    def setUp(self):
        self.data = pd.DataFrame({
            'total_elec_kwh': [20, 20, 2000, 2000, 2000],
            'flag_energy_capacity_mismatch': [False, False, True, True, False],
            'flag_missing_equipment_or_power': [False, True, False, True, False],
        })

    def test_v2_union_counts_overlap_once(self):
        excluded, reasons, extreme, missing = exclusion_rules(self.data, 2)
        self.assertEqual(excluded.tolist(), [False, True, True, True, False])
        self.assertEqual(int(excluded.sum()), int(extreme.sum() + missing.sum() - (extreme & missing).sum()))
        self.assertIn(';', reasons[3])

    def test_v1_does_not_exclude_missing_alone(self):
        excluded, reasons, _, _ = exclusion_rules(self.data, 1)
        self.assertEqual(excluded.tolist(), [False, False, True, True, False])
        self.assertEqual(reasons[1], '')


if __name__ == '__main__':
    unittest.main()
