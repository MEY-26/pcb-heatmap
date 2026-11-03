"""Actionable bilingual electrothermal failures preserve per-net current meaning."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from i18n import format_analysis_error


class AnalysisMessageTests(unittest.TestCase):
    def details(self):
        return dict(iteration=3, computed_peak_c=1600, previous_peak_c=400,
                    model_limit_c=1500, mesh_cell_mm=.25,
                    convection_top=10, convection_bottom=10,
                    net_loads=[dict(net='/VBAT+', draw_a=1040, injection_a=0, signed_a=1040, group_count=13),
                               dict(net='GND', draw_a=0, injection_a=320, signed_a=-320, group_count=4)])

    def test_turkish_reports_13_group_1040a_and_separate_ground_return(self):
        details = self.details()
        before = deepcopy(details)
        message = format_analysis_error('electrothermal_outside_validity', details, 'tr')
        self.assertIn('/VBAT+: 13 grup; çekilen 1040 A; verilen 0 A.', message)
        self.assertIn('GND: 4 grup; çekilen 0 A; verilen 320 A.', message)
        self.assertNotIn('720 A', message, 'Ground return must not cancel VBAT loading in the message.')
        self.assertIn('1500 °C', message)
        self.assertIn('gerçek kartın ulaşacağı sıcaklık tahmini değildir', message)
        self.assertIn('diğer satırlara otomatik bölünmez', message)
        self.assertIn('Yinelenen yükleri', message)
        self.assertEqual(details, before)

    def test_english_default_is_actionable_without_claiming_safe_temperature(self):
        message = format_analysis_error('electrothermal_outside_validity', self.details())
        self.assertIn('no valid temperature map', message)
        self.assertIn('iteration 3', message)
        self.assertIn('/VBAT+: 13 groups; draw 1040 A; injection 0 A.', message)
        self.assertIn('not a prediction of the actual board temperature', message)
        self.assertIn('Check duplicate loads and intended group totals', message)

    def test_nonfinite_and_nonconvergence_have_distinct_translations(self):
        for language, expected in [('en', 'nonfinite values'), ('tr', 'geçerli sayısal sıcaklık')]:
            details = self.details(); details['computed_peak_c'] = None
            message = format_analysis_error('electrothermal_nonfinite', details, language)
            self.assertIn(expected, message)
            self.assertNotIn('None', message)
        for language, expected in [('en', 'did not converge'), ('tr', 'sabit bir sonuca ulaşmadı')]:
            self.assertIn(expected, format_analysis_error('electrothermal_nonconvergence', self.details(), language))

    def test_unknown_or_missing_details_use_safe_fallbacks(self):
        self.assertIsNone(format_analysis_error('unrelated_error', self.details(), 'tr'))
        self.assertIsNone(format_analysis_error(None, None))
        self.assertIn('no valid temperature map', format_analysis_error('nonfinite', None))
        malformed = dict(net_loads=[None, dict(net='BAD', draw_a=float('nan'), injection_a=0)], iteration=float('inf'))
        message = format_analysis_error('nonconvergence', malformed)
        self.assertNotIn('nan', message)
        self.assertNotIn('inf', message)


if __name__ == '__main__':
    unittest.main()
