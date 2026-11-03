"""KiCad ActionPlugin entry. No board mutation or network activity."""
from pathlib import Path
import pcbnew
import wx

_plugin = None
_frame = None


class PCBHeatmapPlugin(pcbnew.ActionPlugin):
    def defaults(self):
        self.name = 'PCB Heatmap'
        self.category = 'PCB analysis'
        self.description = 'Read-only local DC and steady-state thermal heatmaps'
        self.show_toolbar_button = True
        self.icon_file_name = str(Path(__file__).with_name('toolbar-24.png'))

    def Run(self):
        global _frame
        from .visual_gui import VisualFrame
        if _frame is not None:
            try:
                if not _frame.IsBeingDeleted():
                    _frame.Show()
                    _frame.Raise()
                    return
            except RuntimeError:
                pass
        board = pcbnew.GetBoard()
        path = board.GetFileName() if board else ''
        if not path:
            wx.MessageBox('Save the PCB first. PCB Heatmap reads the saved file only.',
                          'PCB Heatmap', wx.OK | wx.ICON_INFORMATION)
            return
        _frame = VisualFrame(board_path=path, pcb_context=True)
        _frame.Show()


def register_plugin():
    global _plugin
    if _plugin is None:
        _plugin = PCBHeatmapPlugin()
        _plugin.register()
