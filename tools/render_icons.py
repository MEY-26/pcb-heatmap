"""Render the editable PCB Heatmap SVG at exact KiCad toolbar/PCM sizes."""
from pathlib import Path

import wx
import wx.svg


def render():
    source = Path(__file__).resolve().parents[1] / 'pcb_heatmap'
    app = wx.GetApp() or wx.App(False)
    artwork = wx.svg.SVGimage.CreateFromFile(str(source / 'icon.svg'))
    for size, name in ((24, 'toolbar-24.png'), (48, 'toolbar-48.png'),
                       (64, 'pcm-icon.png')):
        bitmap = artwork.ConvertToBitmap(scale=size / 64, width=size, height=size)
        path = source / name
        if not bitmap.IsOk() or not bitmap.SaveFile(str(path), wx.BITMAP_TYPE_PNG):
            raise RuntimeError('Could not render ' + str(path))
        print(path)


if __name__ == '__main__':
    render()
