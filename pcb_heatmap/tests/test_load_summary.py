"""Load bookkeeping, including the failed thirteen-row user scenario shape."""
import copy
import unittest

from pcb_heatmap.model import AnalysisError, duplicate_terminal_groups, load_totals


class LoadSummaryTests(unittest.TestCase):
    def test_thirteen_groups_count_once_each_not_per_pad(self):
        pads, rows = {}, []
        for component in range(12):
            ids = [f'u{component}.{pin}' for pin in range(5, 9)]
            pads.update({i: dict(net='VBAT') for i in ids})
            rows.append(dict(kind='load', pad_ids=ids, value=80))
        rows.insert(4, copy.deepcopy(rows[3]))
        before = copy.deepcopy(rows)
        result = load_totals(rows, pads)
        self.assertEqual(result, [dict(net='VBAT', draw_a=1040, injection_a=0, signed_a=1040, group_count=13)])
        duplicates = duplicate_terminal_groups(rows)
        self.assertEqual([(i['first_index'], i['duplicate_index']) for i in duplicates], [(3, 4)])
        self.assertEqual(rows, before)

    def test_forward_and_return_currents_stay_separate(self):
        pads = dict(a=dict(net='VBAT'), b=dict(net='GND'), c=dict(net='VBAT'))
        rows = [dict(kind='load', pad_ids=['a'], value=320),
                dict(kind='load', pad_ids=['b'], value=-320),
                dict(kind='load', pad_ids=['c'], value=-10),
                dict(kind='source', pad_ids=['a'], value=33.6)]
        results = {t['net']: t for t in load_totals(rows, pads)}
        self.assertEqual(results['VBAT']['draw_a'], 320)
        self.assertEqual(results['VBAT']['injection_a'], 10)
        self.assertEqual(results['GND']['injection_a'], 320)
        self.assertEqual(results['GND']['draw_a'], 0)

    def test_duplicate_group_is_pad_order_independent_and_kind_specific(self):
        rows = [dict(kind='load', pad_ids=['a', 'b'], value=1),
                dict(kind='source', pad_ids=['a', 'b'], value=1),
                dict(kind='load', pad_ids=['b', 'a'], value=2)]
        self.assertEqual(len(duplicate_terminal_groups(rows)), 1)
        self.assertEqual(duplicate_terminal_groups(rows)[0]['duplicate_index'], 2)

    def test_analysis_error_remains_backward_compatible(self):
        plain = AnalysisError('old message')
        self.assertEqual(str(plain), 'old message')
        self.assertIsNone(plain.code)
        self.assertEqual(plain.details, {})
        structured = AnalysisError('detail', code='code', details=dict(total_draw_a=1040))
        self.assertEqual(structured.details['total_draw_a'], 1040)


if __name__ == '__main__':
    unittest.main()
