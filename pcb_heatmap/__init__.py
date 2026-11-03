"""PCB Heatmap: registration only inside KiCad's legacy plugin loader."""
import os
import sys

__version__ = '0.3.4'

if os.environ.get('PCB_HEATMAP_HEADLESS') != '1' and 'pcbnew' in sys.modules:
    # A standalone process can import the package without opening any UI.
    try:
        import wx
        if wx.GetApp() is not None:
            from .plugin import register_plugin
            register_plugin()
    except ImportError:
        pass
