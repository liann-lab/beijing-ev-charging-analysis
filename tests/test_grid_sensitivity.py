import sys
from pathlib import Path
import unittest
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from analyze_grid_sensitivity import aggregate,display_sample


class GridSensitivityTests(unittest.TestCase):
    def test_display_rules_are_distinct_and_include_five(self):
        g=pd.DataFrame({'orders':[4,5,100],'guns':[5,4,10]})
        self.assertEqual(display_sample(g,'mean_energy').index.tolist(),[1,2])
        self.assertEqual(display_sample(g,'utilization').index.tolist(),[0,2])
        self.assertEqual(len(g),3)

    def test_aggregation_uses_unique_station_capacity_and_duration(self):
        s=pd.DataFrame({'month':['2025-01']*2,'station_id':['a','b'],'grid_id':['1_2']*2,
            'monthly_order_count':[2,3],'monthly_total_elec_kwh':[20.,60.],
            'monthly_duration_min':[1440.,2880.],'charging_gun_num':[1.,2.]})
        g=aggregate(s)
        self.assertEqual(g.orders.iloc[0],5)
        self.assertEqual(g.mean_energy.iloc[0],16)
        self.assertAlmostEqual(g.utilization.iloc[0],1/31)
        with self.assertRaises(ValueError):aggregate(pd.concat([s,s]))
