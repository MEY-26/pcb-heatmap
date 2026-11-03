"""Run explicit test groups without pretending hosted CI includes native KiCad.

Run from the repository root. Portable and package checks need only the
development requirements. GUI checks additionally need wxPython on Windows.
Native checks require KiCad 10's bundled Python and pcbnew; no test is silently
skipped when that runtime is absent.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / 'pcb_heatmap' / 'tests'
PORTABLE_MODULES = (
    'test_analysis_messages', 'test_contacts', 'test_dc_diagnostic',
    'test_generic_inputs', 'test_load_summary', 'test_preferences',
    'test_solver', 'test_solver_acceleration', 'test_solver_diagnostics',
    'test_validation',
)
GUI_MODULES = (
    'test_light_buttons', 'test_light_controls', 'test_settings_gui',
    'test_visual_editing',
)
NATIVE_MODULES = (
    'test_snapshot', 'test_worker', 'test_visual_worker',
    'pcb_heatmap.test_extractor_native', 'pcb_heatmap.test_layout_export',
)
NATIVE_MATERIAL_TEST = 'test_native_worker_metal_core_writes_dc_only_never_temperature'


def tests_for(group):
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    if group in ('portable', 'all'):
        suite.addTests(loader.loadTestsFromNames(PORTABLE_MODULES))
        materials = importlib.import_module('test_materials').MaterialTests
        for name in loader.getTestCaseNames(materials):
            if name != NATIVE_MATERIAL_TEST:
                suite.addTest(materials(name))
    if group in ('gui', 'all'):
        suite.addTests(loader.loadTestsFromNames(GUI_MODULES))
    if group in ('native', 'all'):
        suite.addTests(loader.loadTestsFromNames(NATIVE_MODULES))
        suite.addTests(loader.loadTestsFromName('test_materials.MaterialTests.' + NATIVE_MATERIAL_TEST))
    if group in ('package', 'all'):
        suite.addTests(loader.loadTestsFromName('test_package'))
    return suite


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group', choices=('portable', 'gui', 'native', 'package', 'all'))
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    os.environ['PCB_HEATMAP_HEADLESS'] = '1'
    sys.path[:0] = [str(ROOT), str(TESTS)]
    if args.group in ('gui', 'all') and importlib.util.find_spec('wx') is None:
        parser.error('GUI checks require wxPython; use Windows and install wxPython==4.2.2.')
    if args.group in ('native', 'all') and importlib.util.find_spec('pcbnew') is None:
        parser.error('Native checks require KiCad 10 bundled Python with pcbnew; they were not run.')
    suite = tests_for(args.group)
    count = suite.countTestCases()
    print(f'Running {args.group} checks: {count} tests.', flush=True)
    if args.group in ('portable', 'gui', 'package'):
        print('Native KiCad geometry/worker integration checks are a separate explicit group: '
              'run ci/run_tests.py native using KiCad 10 bundled Python.', flush=True)
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
