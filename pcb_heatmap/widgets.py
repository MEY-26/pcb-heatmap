"""Composed widgets for the plugin window.

These are thin layers over the locally painted controls: buttons, segments,
status pills, the tool rail, the map legend and message bands.  They own only
their own pixels and never restyle a KiCad window.  Every colour comes from a
:class:`pcb_heatmap.theme.Palette`, so ``SetPalette`` is enough to switch
appearance live.
"""
from __future__ import annotations

import wx

from . import icons
from .ui_controls import LightButton, LightToggleButton


def _graphics(dc):
    try:
        return wx.GraphicsContext.Create(dc)
    except Exception:
        return None


def _elide(measure, label, width):
    if width <= 0:
        return ''
    if measure(label)[0] <= width:
        return label
    while label and measure(label + '\u2026')[0] > width:
        label = label[:-1]
    return label + '\u2026' if label else ''


def ui_font(point=None, weight=None):
    """The system UI font at a requested size/weight."""
    base = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
    chosen = wx.Font(base)
    if point is not None:
        chosen.SetPointSize(max(6, int(point)))
    if weight is not None:
        chosen.SetWeight(weight)
    return chosen


def blend(first, second, amount):
    a, b = wx.Colour(first), wx.Colour(second)
    amount = max(0.0, min(1.0, float(amount)))
    return wx.Colour(
        int(round(a.Red() + (b.Red() - a.Red()) * amount)),
        int(round(a.Green() + (b.Green() - a.Green()) * amount)),
        int(round(a.Blue() + (b.Blue() - a.Blue()) * amount)))


def readable(background, palette):
    return palette.text if wx.Colour(background).GetLuminance() < 0.45 else palette.accent_text


class Divider(wx.Control):
    """One-pixel horizontal rule, colour-managed by the palette."""

    def __init__(self, parent, colour=None):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize((-1, self.FromDIP(1)))
        self._colour = colour
        self.Bind(wx.EVT_PAINT, self._paint)

    def SetColour(self, colour):
        self._colour = colour
        self.Refresh()

    def _paint(self, event):
        dc = wx.PaintDC(self)
        dc.SetBackground(wx.Brush(self.GetParent().GetBackgroundColour()))
        dc.Clear()
        colour = self._colour or wx.Colour('#3a4046')
        dc.SetPen(wx.Pen(colour, 1))
        width, height = self.GetClientSize()
        dc.DrawLine(0, height // 2, width, height // 2)


class Pill(wx.Control):
    """Compact status chip: Ready / Reading / Solving / Done / Error."""

    TONES = {'info': 'accent', 'ok': 'ok', 'warn': 'warning',
             'error': 'danger', 'muted': 'muted'}

    def __init__(self, parent, text='', tone='info'):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetLabel(text or '')
        self._tone = tone
        self._palette = None
        self.SetFont(ui_font(None))
        self.Bind(wx.EVT_PAINT, self._paint)

    def ApplyPalette(self, palette):
        self._palette = palette
        self._refresh_size()
        self.Refresh()

    def SetTone(self, tone):
        self._tone = tone if tone in ('info', 'ok', 'warn', 'error', 'muted') else 'info'
        self.Refresh()

    def SetLabel(self, text):
        super().SetLabel(str(text))
        if hasattr(self, '_palette'):
            self._refresh_size()
        self.Refresh()

    def _colour(self):
        palette = self._palette
        if palette is None:
            import wx as _wx
            return _wx.Colour('#007e87')
        return wx.Colour(getattr(palette, self.TONES.get(self._tone, 'accent'), palette.accent))

    def _refresh_size(self):
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        width, height = dc.GetTextExtent(self.GetLabel())
        self.SetMinSize((width + self.FromDIP(22), max(self.FromDIP(22), height + self.FromDIP(8))))
        self.InvalidateBestSize()

    def DoGetBestSize(self):
        return self.GetMinSize()

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        parent = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(parent))
        dc.Clear()
        palette = self._palette
        tone = self._colour()
        background = blend(parent, tone, 0.20)
        gc = _graphics(dc)
        width, height = self.GetClientSize()
        if gc is not None:
            gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)
            gc.SetPen(wx.Pen(tone, 1))
            gc.SetBrush(wx.Brush(background))
            gc.DrawRoundedRectangle(0.5, 0.5, max(1, width - 1), max(1, height - 1),
                                    self.FromDIP(9))
            gc.SetFont(self.GetFont(), tone)
            text = self.GetLabel()
            tw, th = gc.GetTextExtent(text)
            gc.DrawText(text, (width - tw) // 2, (height - th) // 2)
            return
        dc.SetPen(wx.Pen(tone, 1))
        dc.SetBrush(wx.Brush(background))
        dc.DrawRectangle(0, 0, width, height)
        dc.SetFont(self.GetFont())
        dc.SetTextForeground(tone)
        tw, th = dc.GetTextExtent(self.GetLabel())
        dc.DrawText(self.GetLabel(), (width - tw) // 2, (height - th) // 2)


class PushButton(LightButton):
    """Rounded button with a primary (accent) and a quiet role."""

    def __init__(self, parent, label='', role='secondary', glyph=None, **kwargs):
        super().__init__(parent, label=label, **kwargs)
        self.role = role
        self.glyph = glyph
        self.SetFont(ui_font(None))
        self.palette = None
        self.SetMinSize((self.FromDIP(112 if role == 'primary' else 88), self.FromDIP(34)))

    def ApplyPalette(self, palette):
        self.palette = palette
        self.Refresh()

    def DoGetBestSize(self):
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        width = dc.GetTextExtent(self.GetLabelText())[0] + self.FromDIP(56 if self.glyph else 28)
        return wx.Size(max(self.FromDIP(112 if self.role == 'primary' else 88), width),
                       self.FromDIP(34))

    def _paint(self, event):
        self._draw(wx.AutoBufferedPaintDC(self))

    def _draw(self, dc):
        palette = getattr(self, 'palette', None)
        if palette is None:
            try:
                from . import ui_controls
                palette = ui_controls.palette()
            except Exception:
                palette = None
        if palette is None:
            return super()._draw(dc)
        width, height = self.GetClientSize()
        if width < 1 or height < 1:
            return
        enabled = self.IsEnabled()
        pressed = self._mouse_pressed and self._hovered
        gc = _graphics(dc)
        if gc is None:
            return super()._draw(dc)
        parent = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(parent))
        dc.Clear()
        gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)
        accent = wx.Colour(palette.accent)
        if self.role == 'primary':
            face = blend(parent, accent, 0.75 if not enabled else (1.0 if not pressed else 0.86))
            if self._hovered and enabled:
                face = blend(face, wx.Colour(palette.accent_hover), 0.55)
            text = wx.Colour(palette.accent_text)
            border = face
        else:
            face = wx.Colour(palette.panel_alt if not self._hovered else palette.accent_soft)
            if pressed:
                face = wx.Colour(palette.selection)
            text = wx.Colour(palette.text if enabled else palette.muted)
            border = wx.Colour(palette.accent if self.HasFocus() else palette.border)
        gc.SetBrush(wx.Brush(face))
        gc.SetPen(wx.Pen(border, 1))
        gc.DrawRoundedRectangle(0.5, 0.5, width - 1, height - 1, self.FromDIP(7))
        gc.SetFont(self.GetFont(), text)
        label = self.GetLabelText()
        label_width = gc.GetTextExtent(label)[0] if label else 0
        gap = self.FromDIP(7) if self.glyph else 0
        icon_size = self.FromDIP(17)
        total = label_width + (icon_size + gap if self.glyph else 0)
        x = (width - total) // 2
        if self.glyph:
            icons.draw(gc, self.glyph, wx.Rect(x, (height - icon_size) // 2, icon_size, icon_size),
                       text)
            x += icon_size + gap
        gc.DrawText(label, x, (height - gc.GetTextExtent(label)[1]) // 2)
        if self.HasFocus() and enabled:
            gc.SetPen(wx.Pen(wx.Colour(palette.accent), 1))
            gc.SetBrush(wx.Brush(wx.Colour(palette.accent), wx.BRUSHSTYLE_TRANSPARENT))
            gc.DrawRoundedRectangle(2.5, 2.5, width - 5, height - 5, self.FromDIP(5))


class IconButton(LightButton):
    """Square glyph button used by the tool rail and canvas overlays."""

    def __init__(self, parent, glyph='board', tooltip='', size=(38, 38), checkable=False):
        super().__init__(parent, label='', size=size)
        self.glyph = glyph
        self.checkable = checkable
        self.active = False
        self.SetMinSize(size)
        self.SetToolTip(tooltip)
        self.SetName(tooltip or glyph)
        self.palette = None

    def ApplyPalette(self, palette):
        self.palette = palette
        self.Refresh()

    def SetActive(self, active):
        self.active = bool(active)
        self.Refresh()

    def SetGlyph(self, glyph):
        self.glyph = glyph
        self.Refresh()

    def DoGetBestSize(self):
        return self.GetMinSize()

    def _paint(self, event):
        self._draw(wx.AutoBufferedPaintDC(self))

    def _draw(self, dc):
        palette = getattr(self, 'palette', None)
        if palette is None:
            try:
                from . import ui_controls
                palette = ui_controls.palette()
            except Exception:
                palette = None
        if palette is None:
            return super()._draw(dc)
        width, height = self.GetClientSize()
        if width < 1 or height < 1:
            return
        parent = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(parent))
        dc.Clear()
        gc = _graphics(dc)
        if gc is None:
            return super()._draw(dc)
        gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)
        enabled = self.IsEnabled()
        if self.active:
            background = wx.Colour(palette.accent_soft)
            glyph_colour = wx.Colour(palette.accent)
        elif self._mouse_pressed and self._hovered:
            background = wx.Colour(palette.selection)
            glyph_colour = wx.Colour(palette.text)
        elif self._hovered:
            background = blend(parent, wx.Colour(palette.accent), 0.12)
            glyph_colour = wx.Colour(palette.text)
        else:
            background = None
            glyph_colour = wx.Colour(palette.muted if enabled else palette.disabled)
        if background is not None:
            gc.SetBrush(wx.Brush(background))
            gc.SetPen(wx.Pen(background, 1))
            gc.DrawRoundedRectangle(0.5, 0.5, width - 1, height - 1, self.FromDIP(7))
        inset = self.FromDIP(9)
        icons.draw(gc, self.glyph, wx.Rect(inset, inset, width - 2 * inset, height - 2 * inset),
                   glyph_colour)
        if self.HasFocus() and enabled:
            gc.SetPen(wx.Pen(wx.Colour(palette.accent), 1))
            gc.SetBrush(wx.Brush(wx.Colour(palette.accent), wx.BRUSHSTYLE_TRANSPARENT))
            gc.DrawRoundedRectangle(1.5, 1.5, width - 3, height - 3, self.FromDIP(6))


class ToolRail(wx.Panel):
    """Vertical section switcher, KiCad-style."""

    def __init__(self, parent, items=(), on_select=None):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._palette = None
        self._on_select = on_select
        self.buttons = {}
        self._keys = []
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.AddSpacer(self.FromDIP(8))
        for key, glyph, tooltip in items:
            button = IconButton(self, glyph, tooltip, size=(self.FromDIP(38), self.FromDIP(38)))
            button.Bind(wx.EVT_BUTTON, lambda event, name=key: self.select(name, notify=True))
            sizer.Add(button, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, self.FromDIP(6))
            self.buttons[key] = button
            self._keys.append(key)
        sizer.AddStretchSpacer()
        self.SetSizer(sizer)
        self.SetMinSize((self.FromDIP(50), -1))
        self.Bind(wx.EVT_PAINT, self._paint)

    def ApplyPalette(self, palette):
        self._palette = palette
        for button in self.buttons.values():
            button.ApplyPalette(palette)
        self.Refresh()

    def select(self, key, notify=False):
        if key not in self.buttons:
            return
        for name, button in self.buttons.items():
            button.SetActive(name == key)
        if notify and self._on_select:
            self._on_select(key)

    def selected(self):
        for key, button in self.buttons.items():
            if button.active:
                return key
        return None

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        palette = self._palette
        background = wx.Colour(palette.panel_alt if palette else '#f7fafc')
        dc.SetBackground(wx.Brush(background))
        dc.Clear()
        width, height = self.GetClientSize()
        if palette is not None:
            dc.SetPen(wx.Pen(wx.Colour(palette.divider), 1))
            dc.DrawLine(width - 1, 0, width - 1, height)


class SegmentedControl(wx.Control):
    """Rounded segmented control for map views and terminal tools."""

    def __init__(self, parent, labels=(), on_select=None, size=(-1, -1)):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._labels = [str(label) for label in labels]
        self._selection = 0 if self._labels else wx.NOT_FOUND
        self._hover = wx.NOT_FOUND
        self._palette = None
        self._on_select = on_select
        self._rects = []
        self.SetFont(ui_font(None))
        self.SetMinSize((size[0] if size[0] > 0 else -1, self.FromDIP(32)))
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_LEFT_UP, self._click)
        self.Bind(wx.EVT_MOTION, self._motion)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._leave)
        self.Bind(wx.EVT_KEY_DOWN, self._key)
        self.Bind(wx.EVT_LEFT_DOWN, lambda event: self.SetFocus())

    def ApplyPalette(self, palette):
        self._palette = palette
        self.Refresh()

    def Set(self, labels, selection=None):
        self._labels = [str(label) for label in labels]
        self._selection = 0 if self._labels and selection is None else (
            wx.NOT_FOUND if not self._labels else max(0, min(len(self._labels) - 1,
                                                            self._selection if selection is None else selection)))
        self.InvalidateBestSize()
        self.Refresh()

    def GetCount(self):
        return len(self._labels)

    def GetStrings(self):
        return list(self._labels)

    def GetSelection(self):
        return self._selection

    def GetStringSelection(self):
        if 0 <= self._selection < len(self._labels):
            return self._labels[self._selection]
        return ''

    def SetSelection(self, index):
        if index == wx.NOT_FOUND or not self._labels:
            self._selection = wx.NOT_FOUND
        else:
            self._selection = max(0, min(len(self._labels) - 1, int(index)))
        self.Refresh()

    def emit(self):
        if self._on_select:
            self._on_select(self._selection)
            return
        event = wx.CommandEvent(wx.EVT_CHOICE.typeId, self.GetId())
        event.SetEventObject(self)
        event.SetInt(self._selection)
        event.SetString(self.GetStringSelection())
        self.GetEventHandler().ProcessEvent(event)

    def DoGetBestSize(self):
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        width = sum(dc.GetTextExtent(label)[0] + self.FromDIP(26) for label in self._labels)
        return wx.Size(width + self.FromDIP(8), self.FromDIP(32))

    def _segment_rects(self, width, height):
        pad = self.FromDIP(2)
        available = max(1, width - 2 * pad)
        weights = []
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        for label in self._labels:
            weights.append(dc.GetTextExtent(label)[0] + self.FromDIP(26))
        total = sum(weights) or 1
        rects, x = [], pad
        for weight in weights:
            segment = max(1, int(round(available * weight / total)))
            rects.append(wx.Rect(x, pad, segment, max(1, height - 2 * pad)))
            x += segment
        return rects

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        palette = self._palette
        parent = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(parent))
        dc.Clear()
        gc = _graphics(dc)
        width, height = self.GetClientSize()
        if gc is None or not self._labels:
            return
        gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)
        track = wx.Colour(palette.panel_alt if palette else '#edf4f7')
        border = wx.Colour(palette.border if palette else '#ccd8e1')
        gc.SetBrush(wx.Brush(track))
        gc.SetPen(wx.Pen(border, 1))
        gc.DrawRoundedRectangle(0.5, 0.5, max(1, width - 1), max(1, height - 1),
                                self.FromDIP(8))
        self._rects = self._segment_rects(width, height)
        for index, rect in enumerate(self._rects):
            selected = index == self._selection
            if selected:
                background = wx.Colour(palette.selection if palette else '#dceff0')
                colour = wx.Colour(palette.accent if palette else '#007e87')
            elif index == self._hover:
                background = blend(parent if not palette else wx.Colour(palette.panel_alt),
                                   wx.Colour(palette.accent if palette else '#007e87'), 0.10)
                colour = wx.Colour(palette.text if palette else '#172e43')
            else:
                background = None
                colour = wx.Colour(palette.muted if palette else '#61768a')
            if background is not None:
                gc.SetBrush(wx.Brush(background))
                gc.SetPen(wx.Pen(background, 1))
                gc.DrawRoundedRectangle(rect.x + 1.0, rect.y + 1.0, rect.width - 2.0,
                                        rect.height - 2.0, self.FromDIP(6))
            gc.SetFont(self.GetFont(), colour)
            label = _elide(gc.GetTextExtent, self._labels[index], rect.width - self.FromDIP(8))
            tw, th = gc.GetTextExtent(label)
            gc.DrawText(label, rect.x + (rect.width - tw) // 2, rect.y + (rect.height - th) // 2)
        if self.HasFocus():
            gc.SetPen(wx.Pen(wx.Colour(palette.accent if palette else '#007e87'), 1))
            gc.SetBrush(wx.Brush(wx.Colour(palette.accent if palette else '#007e87'),
                                 wx.BRUSHSTYLE_TRANSPARENT))
            gc.DrawRoundedRectangle(2.0, 2.0, max(1, width - 4), max(1, height - 4),
                                    self.FromDIP(6))

    def _index_at(self, point):
        if not self._rects:
            self._rects = self._segment_rects(*self.GetClientSize())
        for index, rect in enumerate(self._rects):
            if rect.Contains(point):
                return index
        return wx.NOT_FOUND

    def _motion(self, event):
        index = self._index_at(event.GetPosition())
        if index != self._hover:
            self._hover = index
            self.Refresh()
        event.Skip()

    def _leave(self, event):
        if self._hover != wx.NOT_FOUND:
            self._hover = wx.NOT_FOUND
            self.Refresh()
        event.Skip()

    def _click(self, event):
        index = self._index_at(event.GetPosition())
        if index != wx.NOT_FOUND:
            self.SetFocus()
            if index != self._selection:
                self.SetSelection(index)
            self.emit()

    def _key(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_HOME, wx.WXK_END):
            count = len(self._labels)
            if count:
                if key == wx.WXK_HOME:
                    index = 0
                elif key == wx.WXK_END:
                    index = count - 1
                else:
                    index = (self._selection + (1 if key == wx.WXK_RIGHT else -1)) % count
                self.SetSelection(index)
                self.emit()
                return
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE):
            self.emit()
            return
        event.Skip()


class Legend(wx.Control):
    """Gradient bar with ticks and units for the current overlay scale."""

    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._palette = None
        self._ramp = 'rainbow'
        self._low = 0.0
        self._high = 1.0
        self._units = ''
        self.SetMinSize((-1, self.FromDIP(62)))
        self.Bind(wx.EVT_PAINT, self._paint)

    def ApplyPalette(self, palette):
        self._palette = palette
        self.Refresh()

    def SetScale(self, low, high, units='', ramp=None):
        self._low, self._high = float(low), float(high)
        self._units = str(units or '')
        if ramp:
            self._ramp = ramp
        self.Refresh()

    def SetRamp(self, ramp):
        self._ramp = ramp
        self.Refresh()

    def DoGetBestSize(self):
        return wx.Size(self.FromDIP(220), self.FromDIP(62))

    def _paint(self, event):
        from .colormap import format_number, legend_ticks, ramp_colors

        dc = wx.AutoBufferedPaintDC(self)
        palette = self._palette
        parent = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(parent))
        dc.Clear()
        width, height = self.GetClientSize()
        if width < 40 or height < 20:
            return
        gc = _graphics(dc)
        if gc is None:
            return
        gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)
        text_colour = wx.Colour(palette.text if palette else '#172e43')
        muted = wx.Colour(palette.muted if palette else '#61768a')
        gc.SetFont(self.GetFont(), text_colour)
        title = self._units or 'Value'
        gc.DrawText(title, self.FromDIP(2), 0)
        bar_top = self.FromDIP(18)
        bar_height = self.FromDIP(11)
        bar_width = max(20, width - self.FromDIP(4))
        colors = ramp_colors(self._ramp, 96)
        block = bar_width / float(len(colors))
        gc.SetPen(wx.Pen(wx.Colour(palette.border if palette else '#ccd8e1'), 1))
        gc.SetBrush(wx.Brush(wx.Colour(palette.panel if palette else '#ffffff')))
        gc.DrawRectangle(0.5, bar_top - 1.5, bar_width + 1, bar_height + 3)
        for index, colour in enumerate(colors):
            gc.SetBrush(wx.Brush(wx.Colour(int(colour[0]), int(colour[1]), int(colour[2]))))
            gc.SetPen(wx.Pen(wx.Colour(int(colour[0]), int(colour[1]), int(colour[2])), 1))
            x = 2 + index * block
            gc.DrawRectangle(x, bar_top, block + 1, bar_height)
        gc.SetFont(self.GetFont(), muted)
        ticks = legend_ticks(self._low, self._high, 5)
        for position, value in enumerate(ticks):
            fraction = 0.0 if len(ticks) == 1 else position / (len(ticks) - 1.0)
            label = format_number(value)
            tw = gc.GetTextExtent(label)[0]
            x = 2 + fraction * bar_width
            gc.DrawText(label, min(max(0, x - tw / 2.0), width - tw), bar_top + bar_height + self.FromDIP(5))


class MessageBar(wx.Control):
    """Inline notice above the canvas; wraps to the available width."""

    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self._palette = None
        self._text = ''
        self._tone = 'info'
        self._lines = []
        self.SetMinSize((-1, 0))
        self.Hide()
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_SIZE, lambda event: (self.InvalidateBestSize(), event.Skip()))

    def ApplyPalette(self, palette):
        self._palette = palette
        self.Refresh()

    def ShowMessage(self, text, tone='info'):
        self._text = str(text or '')
        self._tone = tone if tone in ('info', 'ok', 'warn', 'error') else 'info'
        self._lines = []
        self.InvalidateBestSize()
        if self._text:
            self.Show()
        else:
            self.Hide()

    def Clear(self):
        self.ShowMessage('', 'info')

    def _tone_colour(self):
        palette = self._palette
        if palette is None:
            return wx.Colour('#007e87')
        return wx.Colour({'info': palette.accent, 'ok': palette.ok,
                          'warn': palette.warning, 'error': palette.danger}[self._tone])

    def _measure(self):
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        width = max(self.FromDIP(160), self.GetClientSize().width - self.FromDIP(34))
        words = self._text.split()
        lines, line = [], ''
        for word in words:
            candidate = (line + ' ' + word).strip()
            if not line or dc.GetTextExtent(candidate)[0] <= width:
                line = candidate
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)
        self._lines = lines
        return dc, lines

    def DoGetBestSize(self):
        if not self._text:
            return wx.Size(-1, 0)
        dc, lines = self._measure()
        height = dc.GetTextExtent('Xg')[1]
        return wx.Size(-1, height * max(1, len(lines)) + self.FromDIP(16))

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        parent = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(parent))
        dc.Clear()
        if not self._text:
            return
        _, lines = self._measure()
        tone = self._tone_colour()
        width, height = self.GetClientSize()
        gc = _graphics(dc)
        if gc is None:
            return
        gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)
        gc.SetBrush(wx.Brush(blend(parent, tone, 0.16)))
        gc.SetPen(wx.Pen(blend(parent, tone, 0.34), 1))
        gc.DrawRoundedRectangle(0.5, 0.5, max(1, width - 1), max(1, height - 1), self.FromDIP(6))
        gc.SetPen(wx.Pen(tone, 3))
        gc.StrokeLine(2.5, self.FromDIP(5), 2.5, height - self.FromDIP(5))
        gc.SetFont(self.GetFont(), wx.Colour(self._palette.text if self._palette else '#172e43'))
        line_height = gc.GetTextExtent('Xg')[1]
        y = (height - line_height * len(lines)) // 2
        for line in lines:
            gc.DrawText(line, self.FromDIP(14), y)
            y += line_height
