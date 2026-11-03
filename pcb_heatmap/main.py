"""Standalone launcher using the same read-only GUI as the KiCad action."""
from __future__ import annotations
import argparse
import importlib.util
import os
import sys
from pathlib import Path


def main():
    os.environ['PCB_HEATMAP_HEADLESS'] = '1'
    if __package__ in (None, ''):
        package_dir = Path(__file__).resolve().parent
        if 'pcb_heatmap' not in sys.modules:
            spec = importlib.util.spec_from_file_location(
                'pcb_heatmap', package_dir / '__init__.py',
                submodule_search_locations=[str(package_dir)])
            package = importlib.util.module_from_spec(spec)
            sys.modules['pcb_heatmap'] = package
            spec.loader.exec_module(package)
    import wx
    from pcb_heatmap.visual_gui import VisualFrame
    parser = argparse.ArgumentParser(description='Local saved-PCB thermal analysis')
    parser.add_argument('board', nargs='?')
    args = parser.parse_args()
    app = wx.App(False)
    frame = VisualFrame(board_path=args.board)
    frame.Show()
    app.MainLoop()


if __name__ == '__main__':
    main()
