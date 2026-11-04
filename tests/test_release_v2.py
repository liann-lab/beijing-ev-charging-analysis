import sys
from pathlib import Path
import unittest
import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from rebuild_release_v2 import monthly_utilization


class RebuiltUtilizationTests(unittest.TestCase):
    def test_denominator_and_gun_weights(self):
        rates=monthly_utilization(pd.Series([1440.,2880.]),pd.Series([1.,2.]),'2025-01')
        np.testing.assert_allclose(rates,[1/31,1/31])
        self.assertAlmostEqual((rates*pd.Series([1.,2.])).sum()/3,4320/(3*31*1440))

    def test_zero_guns_stays_missing(self):
        self.assertTrue(pd.isna(monthly_utilization(pd.Series([100.]),pd.Series([0.]),'2025-01').iloc[0]))

    def test_june_uses_30_days(self):
        self.assertEqual(monthly_utilization(pd.Series([1440.]),pd.Series([1.]),'2025-06').iloc[0],1/30)
