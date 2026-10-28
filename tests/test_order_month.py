import sys
from pathlib import Path
import unittest
import tempfile
import pandas as pd
import create_visualizations as charts

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from create_visualizations import assign_order_month


class OrderMonthTests(unittest.TestCase):
    def test_cross_month_belongs_to_start_month(self):
        data = pd.DataFrame({'charge_start_time': pd.to_datetime(['2025-06-30 23:50', '2025-07-01 00:10'])})
        self.assertEqual(assign_order_month(data, '2025-07', 'start').tolist(), ['2025-06', '2025-07'])

    def test_january_start_is_january_even_if_end_is_february(self):
        data = pd.DataFrame({'charge_start_time': pd.to_datetime(['2025-01-31 23:50'])})
        self.assertEqual(assign_order_month(data, '2025-01', 'start').tolist(), ['2025-01'])

    def test_previous_file_basis_can_be_reproduced(self):
        data = pd.DataFrame({'charge_start_time': pd.to_datetime(['2025-06-30'])})
        self.assertEqual(assign_order_month(data, '2025-07', 'file').tolist(), ['2025-07'])

    def test_order_figures_exclude_june_starts_but_audit_retains_them(self):
        previous_files, previous_basis = charts.ORDER_FILES, charts.MONTH_BASIS
        try:
            with tempfile.TemporaryDirectory() as folder:
                jan, jul = Path(folder) / 'jan.parquet', Path(folder) / 'jul.parquet'
                pd.DataFrame({'charge_start_time': pd.to_datetime(['2025-01-31']),
                              'total_elec_kwh': [10.], 'construction_site': ['居住区']}).to_parquet(jan)
                pd.DataFrame({'charge_start_time': pd.to_datetime(['2025-06-30', '2025-07-01']),
                              'total_elec_kwh': [20., 30.], 'construction_site': ['居住区', '居住区']}).to_parquet(jul)
                charts.ORDER_FILES = {'2025-01': jan, '2025-07': jul}
                charts.MONTH_BASIS = 'start'
                monthly, hourly, sites, samples = charts.collect_order_summaries()
                self.assertEqual(monthly.sessions.tolist(), [1, 1])
                self.assertEqual(monthly.energy_kwh.tolist(), [10., 30.])
                self.assertEqual(hourly.energy_kwh.sum(), 40.)
                self.assertEqual(sites.sessions.sum(), 2)
                self.assertEqual(len(samples), 2)
                june = [r for r in charts.MONTH_ASSIGNMENT_AUDIT if r['assigned_month'] == '2025-06']
                self.assertEqual(june[0]['sessions'], 1)
                self.assertEqual(june[0]['energy_kwh'], 20.)
        finally:
            charts.ORDER_FILES, charts.MONTH_BASIS = previous_files, previous_basis
