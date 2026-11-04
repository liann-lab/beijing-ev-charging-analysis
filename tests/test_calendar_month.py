import sys
from pathlib import Path
import unittest
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from analyze_calendar_month import split_intervals, lorenz


class CalendarMonthTests(unittest.TestCase):
    def data(self, start, end, duration):
        return pd.DataFrame({'station_id':['a'],'source_file':['test'],'source_row':[0],
            'charge_start_time':pd.to_datetime([start]),'charge_end_time':pd.to_datetime([end]),'duration_min':[duration]})

    def test_cross_month_shares_and_recorded_duration_conserve(self):
        q=split_intervals(self.data('2025-06-30 23:30','2025-07-01 00:30',59.9))
        self.assertEqual(q.month.tolist(),['2025-06','2025-07'])
        self.assertEqual(q.overlap_minutes.tolist(),[30.,30.])
        self.assertEqual(q.session_duration_share.tolist(),[.5,.5])
        self.assertAlmostEqual(q.allocated_recorded_minutes.sum(),59.9)

    def test_exact_boundary_does_not_create_new_month_zero(self):
        q=split_intervals(self.data('2025-01-31 23:00','2025-02-01 00:00',60.))
        self.assertEqual(q.month.tolist(),['2025-01'])
        self.assertEqual(q.overlap_minutes.tolist(),[60.])

    def test_leap_month_and_multiple_months(self):
        q=split_intervals(self.data('2024-02-01','2024-04-01',60.*24*60))
        self.assertEqual(q.overlap_minutes.tolist(),[29*1440.,31*1440.])
        self.assertAlmostEqual(q.session_duration_share.sum(),1.)

    def test_invalid_interval_fails(self):
        with self.assertRaises(ValueError): split_intervals(self.data('2025-01-01','2025-01-01',0.))

    def test_concentration(self):
        self.assertAlmostEqual(lorenz([2,2,2])[2],0.)
        self.assertAlmostEqual(lorenz([0,0,3])[2],2/3)
