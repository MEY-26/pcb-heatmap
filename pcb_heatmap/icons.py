"""Small parametric glyphs drawn with a wx.GraphicsContext.

Icons are code, not assets: they inherit the active palette, stay crisp at any
DPI and need no PNG variants.  Each painter works in a 20 × 20 design box.
"""
from __future__ import annotations

import math

import wx


def _pen(gc, colour, width):
    gc.SetPen(wx.Pen(colour, max(1, int(round(width)))))


def _nopen(gc, colour):
    gc.SetPen(wx.Pen(colour, 1, wx.PENSTYLE_TRANSPARENT))


def _stroke(gc, colour, points, width=1.7):
    _pen(gc, colour, width)
    gc.StrokeLines([wx.Point2D(px, py) for px, py in points])


def _fill(gc, colour, points):
    gc.SetBrush(wx.Brush(colour))
    _nopen(gc, colour)
    gc.DrawPolygon([wx.Point2D(px, py) for px, py in points])


def _ring(gc, colour, x, y, w, h, width=1.7):
    _pen(gc, colour, width)
    gc.SetBrush(wx.Brush(colour, wx.BRUSHSTYLE_TRANSPARENT))
    gc.DrawEllipse(x, y, w, h)


def _rounded(gc, colour, x, y, w, h, radius, width=1.7, fill=None):
    _pen(gc, colour, width)
    gc.SetBrush(wx.Brush(fill, wx.BRUSHSTYLE_TRANSPARENT) if fill is None else wx.Brush(fill))
    gc.DrawRoundedRectangle(x, y, w, h, radius)


def _board(gc, colour):
    _rounded(gc, colour, 2.5, 4.0, 15.0, 12.0, 2.4)
    gc.SetBrush(wx.Brush(colour))
    _nopen(gc, colour)
    for x, y in ((6.2, 7.4), (12.4, 7.4), (6.2, 12.2), (12.4, 12.2)):
        gc.DrawRoundedRectangle(x, y, 2.6, 2.2, 0.5)


def _bolt(gc, colour):
    _fill(gc, colour, [(11.6, 1.8), (4.6, 11.2), (9.1, 11.2),
                       (8.2, 18.2), (15.4, 8.6), (10.8, 8.6)])


def _sliders(gc, colour):
    for y, knob in ((6.0, 13.2), (14.0, 6.8)):
        _stroke(gc, colour, [(3.0, y), (17.0, y)])
        gc.SetBrush(wx.Brush(colour))
        _nopen(gc, colour)
        gc.DrawEllipse(knob - 2.1, y - 2.1, 4.2, 4.2)


def _chart(gc, colour):
    _stroke(gc, colour, [(3.4, 2.6), (3.4, 16.6), (17.4, 16.6)])
    gc.SetBrush(wx.Brush(colour))
    _nopen(gc, colour)
    for x, top in ((6.0, 10.8), (9.9, 6.6), (13.8, 9.0)):
        gc.DrawRoundedRectangle(x, top, 2.4, 16.2 - top, 0.6)


def _document(gc, colour):
    _stroke(gc, colour, [(5.0, 2.4), (12.4, 2.4), (16.0, 6.0),
                         (16.0, 17.6), (5.0, 17.6), (5.0, 2.4)])
    _stroke(gc, colour, [(12.4, 2.4), (12.4, 6.0), (16.0, 6.0)])
    _stroke(gc, colour, [(7.6, 10.2), (13.4, 10.2)], 1.4)
    _stroke(gc, colour, [(7.6, 13.2), (13.4, 13.2)], 1.4)


def _help(gc, colour):
    _ring(gc, colour, 2.6, 2.6, 14.8, 14.8)
    _stroke(gc, colour, [(7.4, 8.0), (7.9, 6.9), (9.6, 6.3),
                         (11.3, 7.0), (12.0, 8.4), (11.4, 9.8),
                         (9.8, 10.8), (9.8, 12.2)], 1.5)
    gc.SetBrush(wx.Brush(colour))
    _nopen(gc, colour)
    gc.DrawEllipse(9.1, 13.6, 1.7, 1.7)


def _play(gc, colour):
    _fill(gc, colour, [(6.4, 3.6), (16.4, 10.0), (6.4, 16.4)])


def _chevron(gc, colour):
    _stroke(gc, colour, [(6.4, 8.0), (10.0, 12.0), (13.6, 8.0)], 1.6)


def _search(gc, colour):
    _ring(gc, colour, 3.0, 3.0, 10.6, 10.6)
    _stroke(gc, colour, [(12.6, 12.6), (16.8, 16.8)], 1.8)


def _eye(gc, colour):
    _stroke(gc, colour, [(2.4, 10.0), (6.0, 6.4), (10.0, 5.6),
                         (14.0, 6.4), (17.6, 10.0), (14.0, 13.6),
                         (10.0, 14.4), (6.0, 13.6), (2.4, 10.0)])
    gc.SetBrush(wx.Brush(colour))
    _nopen(gc, colour)
    gc.DrawEllipse(8.1, 8.1, 3.8, 3.8)


def _plus(gc, colour):
    _stroke(gc, colour, [(10.0, 4.2), (10.0, 15.8)], 1.9)
    _stroke(gc, colour, [(4.2, 10.0), (15.8, 10.0)], 1.9)


def _close(gc, colour):
    _stroke(gc, colour, [(5.2, 5.2), (14.8, 14.8)], 1.8)
    _stroke(gc, colour, [(14.8, 5.2), (5.2, 14.8)], 1.8)


def _layers(gc, colour):
    _stroke(gc, colour, [(10.0, 2.8), (17.2, 6.6), (10.0, 10.4), (2.8, 6.6), (10.0, 2.8)], 1.5)
    _stroke(gc, colour, [(3.6, 10.2), (10.0, 13.6), (16.4, 10.2)], 1.5)
    _stroke(gc, colour, [(3.6, 13.6), (10.0, 17.0), (16.4, 13.6)], 1.5)


def _folder(gc, colour):
    _stroke(gc, colour, [(2.8, 5.6), (8.2, 5.6), (9.6, 7.4),
                         (17.2, 7.4), (17.2, 16.2), (2.8, 16.2), (2.8, 5.6)], 1.5)


def _warning(gc, colour):
    _stroke(gc, colour, [(10.0, 2.8), (18.0, 16.8), (2.0, 16.8), (10.0, 2.8)], 1.5)
    _stroke(gc, colour, [(10.0, 7.6), (10.0, 12.0)], 1.6)
    gc.SetBrush(wx.Brush(colour))
    _nopen(gc, colour)
    gc.DrawEllipse(9.2, 13.4, 1.6, 1.6)


def _info(gc, colour):
    _ring(gc, colour, 2.8, 2.8, 14.4, 14.4)
    _stroke(gc, colour, [(10.0, 9.2), (10.0, 13.8)], 1.6)
    gc.SetBrush(wx.Brush(colour))
    _nopen(gc, colour)
    gc.DrawEllipse(9.2, 5.9, 1.6, 1.6)


def _check(gc, colour):
    _stroke(gc, colour, [(4.4, 10.4), (8.4, 14.2), (15.6, 5.8)], 2.0)


def _gear(gc, colour):
    _ring(gc, colour, 7.2, 7.2, 5.6, 5.6, 1.6)
    for angle in range(0, 360, 45):
        radians = math.radians(angle)
        inner = 6.4
        outer = 9.0
        cx = cy = 10.0
        _stroke(gc, colour, [(cx + inner * math.cos(radians), cy + inner * math.sin(radians)),
                             (cx + outer * math.cos(radians), cy + outer * math.sin(radians))], 1.8)


PAINTERS = {
    'board': _board, 'bolt': _bolt, 'sliders': _sliders, 'gear': _gear,
    'chart': _chart, 'document': _document, 'help': _help, 'play': _play,
    'chevron': _chevron, 'search': _search, 'eye': _eye, 'plus': _plus,
    'close': _close, 'layers': _layers, 'folder': _folder, 'warning': _warning,
    'info': _info, 'check': _check,
}

GLYPHS = tuple(sorted(PAINTERS))


def draw(gc, name, rect, colour, stroke=1.7):
    """Paint ``name`` inside ``rect`` using a 20-unit design box."""
    painter = PAINTERS.get(name)
    if painter is None:
        painter = _board
    size = min(rect.width, rect.height)
    if size <= 0:
        return
    scale = size / 20.0
    gc.PushState()
    try:
        gc.Translate(rect.x + (rect.width - size) / 2.0,
                     rect.y + (rect.height - size) / 2.0)
        gc.Scale(scale, scale)
        painter(gc, colour)
    finally:
        gc.PopState()
