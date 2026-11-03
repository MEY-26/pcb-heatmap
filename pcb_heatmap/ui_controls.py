"""Locally painted light controls, independent of KiCad's native dark theme.

The host may enable Windows dark mode process-wide. Native combobox popups,
notebook tabs and list headers can then ignore wx foreground/background colours.
These small controls own those surfaces; no application or system theme changes
are made. The list body remains a normal accessible wx.ListCtrl.
"""
from __future__ import annotations

import builtins
import math

import wx


WHITE = '#ffffff'
TEXT = '#172e43'
MUTED = '#61768a'
LINE = '#ccd8e1'
SOFT = '#edf4f7'
SELECTED = '#dceff0'
ACCENT = '#007e87'


class _LightClickable(wx.Control):
    """Paint every button state locally, including the unchecked check box.

    A colour override on a native Windows button does not cover hover, pressed,
    disabled or unchecked faces when the host has enabled process dark mode.
    These controls use a plain wx.Control and emit the usual command events.
    """
    _kind = 'button'
    _event_type = wx.EVT_BUTTON.typeId

    def __init__(self, parent, id=wx.ID_ANY, label='', pos=wx.DefaultPosition,
                 size=wx.DefaultSize, style=0, validator=wx.DefaultValidator,
                 name='LightButton'):
        super().__init__(parent, id, pos, size,
                         style=wx.BORDER_NONE | wx.WANTS_CHARS,
                         validator=validator, name=name)
        self._hovered = False
        self._mouse_pressed = False
        self._key_pressed = None
        self._value = False
        self._button_style = style
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(WHITE)
        self.SetForegroundColour(TEXT)
        self.SetLabel(label or (wx.GetStockLabel(id) if id != wx.ID_ANY else ''))
        self.SetInitialSize(size)
        for event, handler in ((wx.EVT_PAINT, self._paint),
                               (wx.EVT_LEFT_DOWN, self._down),
                               (wx.EVT_LEFT_UP, self._up),
                               (wx.EVT_MOTION, self._motion),
                               (wx.EVT_ENTER_WINDOW, self._enter),
                               (wx.EVT_LEAVE_WINDOW, self._leave),
                               (wx.EVT_KEY_DOWN, self._key_down),
                               (wx.EVT_KEY_UP, self._key_up),
                               (wx.EVT_SET_FOCUS, self._focus),
                               (wx.EVT_KILL_FOCUS, self._blur),
                               (wx.EVT_MOUSE_CAPTURE_LOST, self._capture_lost),
                               (wx.EVT_WINDOW_DESTROY, self._destroy),
                               (wx.EVT_DPI_CHANGED, self._dpi)):
            self.Bind(event, handler)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda event: None)
        self._top = wx.GetTopLevelParent(self)
        self._top.Bind(wx.EVT_CHAR_HOOK, self._top_key)

    def DoGetBestSize(self):
        width, height = self.GetTextExtent(self.GetLabelText())
        if self._kind == 'checkbox':
            return wx.Size(width+self.FromDIP(28), max(height+self.FromDIP(8), self.FromDIP(28)))
        return wx.Size(max(self.FromDIP(70), width+self.FromDIP(24)),
                       max(self.FromDIP(28), height+self.FromDIP(12)))

    def SetLabel(self, label):
        super().SetLabel(str(label))
        self.InvalidateBestSize()
        self.Refresh()

    def SetFont(self, font):
        changed = super().SetFont(font)
        self.InvalidateBestSize()
        self.Refresh()
        return changed

    def _dpi(self, event):
        self.InvalidateBestSize()
        self.Refresh()
        event.Skip()

    def _inside(self, point):
        return self.GetClientRect().Contains(point)

    def _cancel_press(self):
        self._mouse_pressed = False
        self._key_pressed = None
        if self.HasCapture():
            self.ReleaseMouse()
        self.Refresh()

    def Enable(self, enable=True):
        changed = super().Enable(enable)
        if not enable:
            self._hovered = False
            self._cancel_press()
        self.Refresh()
        return changed

    def Disable(self):
        return self.Enable(False)

    def _down(self, event):
        if not self.IsEnabled():
            return
        self.SetFocus()
        self._mouse_pressed = True
        self._hovered = self._inside(event.GetPosition())
        if not self.HasCapture():
            self.CaptureMouse()
        self.Refresh()

    def _up(self, event):
        activate = self._mouse_pressed and self.IsEnabled() and self._inside(event.GetPosition())
        self._mouse_pressed = False
        if self.HasCapture():
            self.ReleaseMouse()
        self._hovered = self._inside(event.GetPosition())
        self.Refresh()
        if activate:
            self._activate()

    def _enter(self, event):
        self._hovered = self.IsEnabled()
        self.Refresh()
        event.Skip()

    def _leave(self, event):
        self._hovered = False
        self.Refresh()
        event.Skip()

    def _motion(self, event):
        hovered = self.IsEnabled() and self._inside(event.GetPosition())
        if hovered != self._hovered:
            self._hovered = hovered
            self.Refresh()
        event.Skip()

    def _capture_lost(self, event):
        self._mouse_pressed = False
        self._key_pressed = None
        self.Refresh()

    def _focus(self, event):
        self.Refresh()
        event.Skip()

    def _blur(self, event):
        self._cancel_press()
        event.Skip()

    def _key_down(self, event):
        key = event.GetKeyCode()
        if not self.IsEnabled():
            event.Skip()
        elif key == wx.WXK_SPACE:
            self._key_pressed = key
            self.Refresh()
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and self._kind == 'button':
            if self._key_pressed is None:
                self._key_pressed = key
                self._activate()
        elif key == wx.WXK_ESCAPE and (self._key_pressed is not None or self._mouse_pressed):
            self._cancel_press()
        else:
            event.Skip()

    def _key_up(self, event):
        key = event.GetKeyCode()
        active = self._key_pressed == key
        self._key_pressed = None
        self.Refresh()
        if active and key == wx.WXK_SPACE:
            self._activate()
        else:
            event.Skip()

    def _top_key(self, event):
        """Keep mnemonics and dialog Enter behaviour for a non-native button."""
        if not self.IsEnabled() or not self.IsShownOnScreen():
            event.Skip()
            return
        key = event.GetKeyCode()
        if event.AltDown() and 0 <= key <= 0x10ffff:
            label = self.GetLabel().replace('&&', '')
            marker = label.find('&')
            if marker >= 0 and marker+1 < len(label) and label[marker+1].casefold() == chr(key).casefold():
                self.SetFocus()
                self._activate()
                return
        if self._kind == 'button' and key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            focus = wx.Window.FindFocus()
            is_default = self._top.GetDefaultItem() is self
            own_focus = focus is self
            # Native buttons and text fields with explicit Enter handling keep
            # their normal event route. Plain single-line edits use the default.
            other_button = (isinstance(focus, wx.Button) or
                            isinstance(focus, _LightClickable) and focus._kind == 'button') and not own_focus
            own_enter = isinstance(focus, wx.TextCtrl) and bool(
                focus.GetWindowStyle() & (wx.TE_MULTILINE | wx.TE_PROCESS_ENTER))
            if own_focus or (is_default and not other_button and not own_enter):
                if not event.IsAutoRepeat():
                    self._activate()
                return
        event.Skip()

    def _activate(self):
        if not self.IsEnabled():
            return
        if self._kind != 'button':
            self.SetValue(not self._value)
        event = wx.CommandEvent(self._event_type, self.GetId())
        event.SetEventObject(self)
        event.SetString(self.GetLabel())
        if self._kind != 'button':
            event.SetInt(int(self._value))
        # Let unhandled stock ID_OK/ID_CANCEL commands reach wx.Dialog, just as
        # a native button does (including validation and modal return codes).
        self.GetEventHandler().ProcessEvent(event)

    def _destroy(self, event):
        if event.GetEventObject() is self:
            self._cancel_press()
            if self._top:
                self._top.Unbind(wx.EVT_CHAR_HOOK, handler=self._top_key)
        event.Skip()

    def _face(self):
        if not self.IsEnabled():
            return SOFT
        pressed = (self._mouse_pressed and self._hovered) or self._key_pressed is not None
        if pressed or (self._kind == 'toggle' and self._value):
            return SELECTED
        return SOFT if self._hovered else WHITE

    def _paint(self, event):
        self._draw(wx.AutoBufferedPaintDC(self))

    def _draw(self, dc):
        """Shared draw path also permits exact state/pixel regression checks."""
        width, height = self.GetClientSize()
        if width < 1 or height < 1:
            return
        enabled = self.IsEnabled()
        face = self._face() if self._kind != 'checkbox' else (WHITE if enabled else SOFT)
        dc.SetBackground(wx.Brush(face))
        dc.Clear()
        dc.SetFont(self.GetFont())
        dc.SetTextForeground(TEXT if enabled else MUTED)
        pad = self.FromDIP(6)
        if self._kind == 'checkbox':
            side = min(self.FromDIP(15), max(1, height-2))
            rect = wx.Rect(1, (height-side)//2, side, side)
            line = ACCENT if enabled and (self.HasFocus() or self._hovered or self._value) else LINE
            fill = ACCENT if enabled and self._value else (SELECTED if self._value else face)
            dc.SetPen(wx.Pen(line))
            dc.SetBrush(wx.Brush(fill))
            dc.DrawRectangle(rect)
            if self._value:
                dc.SetPen(wx.Pen(WHITE if enabled else MUTED, max(1, self.FromDIP(2))))
                x, y = rect.x, rect.y
                dc.DrawLines([(x+side*2//10, y+side*5//10),
                              (x+side*4//10, y+side*7//10),
                              (x+side*8//10, y+side*3//10)])
            label_x = rect.right+self.FromDIP(7)
            label = _text(dc, self.GetLabelText(), max(0, width-label_x-pad))
        else:
            is_default = self._kind == 'button' and self._top.GetDefaultItem() is self
            line = ACCENT if enabled and (self.HasFocus() or is_default or self._value) else LINE
            dc.SetPen(wx.Pen(line, max(1, self.FromDIP(2)) if is_default else 1))
            dc.SetBrush(wx.Brush(face))
            dc.DrawRectangle(0, 0, width, height)
            label = _text(dc, self.GetLabelText(), max(0, width-2*pad))
            label_width = dc.GetTextExtent(label).width
            label_x = ((width-label_width)//2 if not self._button_style & wx.BU_LEFT else pad)
            if self._button_style & wx.BU_RIGHT:
                label_x = width-pad-label_width
        label_height = dc.GetTextExtent(label).height
        label_y = (height-label_height)//2
        dc.DrawText(label, label_x, label_y)
        if self.HasFocus() and enabled:
            dc.SetPen(wx.Pen(ACCENT, 1, wx.PENSTYLE_DOT))
            # Avoid wx stock transparent brushes: host code may mutate them.
            dc.SetBrush(wx.Brush(WHITE, wx.BRUSHSTYLE_TRANSPARENT))
            if self._kind == 'checkbox' and label_x < width:
                dc.DrawRectangle(max(0, label_x-2), max(0, label_y-1),
                                 min(width-label_x+1, dc.GetTextExtent(label).width+4), label_height+2)
            elif width > 8 and height > 8:
                dc.DrawRectangle(3, 3, width-6, height-6)


class LightButton(_LightClickable):
    """wx.Button subset with locally painted hover/pressed/disabled states."""
    def SetDefault(self):
        previous = self._top.SetDefaultItem(self)
        if previous:
            previous.Refresh()
        self.Refresh()
        return previous


class LightToggleButton(_LightClickable):
    """Two-state toggle; programmatic SetValue never emits a command."""
    _kind = 'toggle'
    _event_type = wx.EVT_TOGGLEBUTTON.typeId

    def GetValue(self):
        return self._value

    def SetValue(self, value):
        self._value = bool(value)
        self.Refresh()


class LightCheckBox(LightToggleButton):
    """Two-state check box with a light unchecked square and focus ring."""
    _kind = 'checkbox'
    _event_type = wx.EVT_CHECKBOX.typeId

    def __init__(self, *args, **kwargs):
        if kwargs.get('style', 0) & wx.CHK_3STATE:
            raise ValueError('LightCheckBox supports two states only')
        super().__init__(*args, **kwargs)

    def IsChecked(self):
        return self.GetValue()


class LightCheckListBox(wx.VListBox):
    """Light checklist for the pad picker; Set and Check remain quiet.

    A row click or Space toggles its check and emits EVT_CHECKLISTBOX with the
    row index. Arrow keys, scrolling and selection use wx.VListBox normally.
    """
    def __init__(self, parent, id=wx.ID_ANY, pos=wx.DefaultPosition,
                 size=wx.DefaultSize, choices=(), style=0, name='LightCheckListBox'):
        super().__init__(parent, id, pos, size,
                         style=wx.BORDER_NONE | wx.WANTS_CHARS, name=name)
        self._items = []
        self._checked = set()
        self.SetBackgroundColour(WHITE)
        self.SetForegroundColour(TEXT)
        self.Bind(wx.EVT_LEFT_UP, self._click)
        self.Bind(wx.EVT_KEY_DOWN, self._key)
        self.Set(choices)

    def Set(self, items):
        self._items = [str(item) for item in items]
        self._checked = set()
        self.SetSelection(wx.NOT_FOUND)
        self.SetItemCount(len(self._items))
        self.Refresh()

    SetItems = Set

    def GetCount(self):
        return len(self._items)

    def GetString(self, index):
        return self._items[index]

    def GetItems(self):
        return list(self._items)

    def Check(self, index, check=True):
        if not 0 <= index < len(self._items):
            raise IndexError('Checklist item is out of range')
        self._checked.add(index) if check else self._checked.discard(index)
        self.RefreshRow(index)

    def IsChecked(self, index):
        if not 0 <= index < len(self._items):
            raise IndexError('Checklist item is out of range')
        return index in self._checked

    def OnMeasureItem(self, index):
        return max(self.FromDIP(28), self.GetCharHeight()+self.FromDIP(10))

    def OnDrawBackground(self, dc, rect, index):
        dc.SetPen(wx.Pen(WHITE, style=wx.PENSTYLE_TRANSPARENT))
        dc.SetBrush(wx.Brush(SELECTED if self.IsSelected(index) else WHITE if self.IsEnabled() else SOFT))
        dc.DrawRectangle(rect)

    def OnDrawItem(self, dc, rect, index):
        dc.SetFont(self.GetFont())
        enabled = self.IsEnabled()
        dc.SetTextForeground(TEXT if enabled else MUTED)
        side = self.FromDIP(15)
        x, y = rect.x+self.FromDIP(6), rect.y+(rect.height-side)//2
        checked = index in self._checked
        dc.SetPen(wx.Pen(ACCENT if checked and enabled else LINE))
        dc.SetBrush(wx.Brush(ACCENT if checked and enabled else WHITE if enabled else SOFT))
        dc.DrawRectangle(x, y, side, side)
        if checked:
            dc.SetPen(wx.Pen(WHITE if enabled else MUTED, max(1, self.FromDIP(2))))
            dc.DrawLines([(x+side*2//10, y+side*5//10),
                          (x+side*4//10, y+side*7//10),
                          (x+side*8//10, y+side*3//10)])
        x += side+self.FromDIP(7)
        label = _text(dc, self._items[index], max(0, rect.right-x-self.FromDIP(6)))
        dc.DrawText(label, x, rect.y+(rect.height-dc.GetTextExtent(label).height)//2)

    def _toggle(self, index):
        if not self.IsEnabled() or not 0 <= index < len(self._items):
            return
        self.SetSelection(index)
        self.Check(index, not self.IsChecked(index))
        event = wx.CommandEvent(wx.EVT_CHECKLISTBOX.typeId, self.GetId())
        event.SetEventObject(self)
        event.SetInt(index)
        event.SetString(self._items[index])
        self.GetEventHandler().ProcessEvent(event)

    def _click(self, event):
        if self.IsEnabled():
            self.SetFocus()
            self._toggle(self.VirtualHitTest(event.GetY()))

    def _key(self, event):
        if self.IsEnabled() and event.GetKeyCode() == wx.WXK_SPACE:
            if not event.IsAutoRepeat():
                self._toggle(self.GetSelection())
        else:
            event.Skip()

    def Enable(self, enable=True):
        changed = super().Enable(enable)
        self.Refresh()
        return changed


def _text(dc, label, width):
    """Elide on the right without painting across adjacent controls."""
    if width <= 0:
        return ''
    if dc.GetTextExtent(label).width <= width:
        return label
    while label and dc.GetTextExtent(label + '\u2026').width > width:
        label = label[:-1]
    return label + '\u2026' if label else ''


class _SpinArrows(wx.Control):
    """Own both arrow faces so Windows never paints disabled dark buttons."""
    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.owner = parent
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(WHITE)
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_LEFT_DOWN, self._click)
        self.Bind(wx.EVT_MOUSEWHEEL, parent._wheel)

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        enabled = self.owner.IsEnabled()
        dc.SetBackground(wx.Brush(WHITE if enabled else SOFT))
        dc.Clear()
        width, height = self.GetClientSize()
        dc.SetPen(wx.Pen(LINE))
        dc.DrawLine(0, 0, 0, height)
        dc.DrawLine(0, height//2, width, height//2)
        dc.SetPen(wx.Pen(TEXT if enabled else MUTED))
        dc.SetBrush(wx.Brush(TEXT if enabled else MUTED))
        delta = self.FromDIP(3)
        for direction, cy in ((1, height//4), (-1, 3*height//4)):
            cx = width//2
            dc.DrawPolygon([(cx-delta, cy+direction*delta//2),
                            (cx+delta, cy+direction*delta//2),
                            (cx, cy-direction*delta)])

    def _click(self, event):
        if self.owner.IsEnabled():
            self.owner._editor.SetFocus()
            self.owner._step(1 if event.GetY() < self.GetClientSize().height//2 else -1)


class LightSpinCtrlDouble(wx.Control):
    """Light numeric editor with wx.SpinCtrlDouble's used public interface.

    KiCad's process-wide Windows dark theme repaints *disabled* native spin
    editors despite their explicit colours. Keep the native text child enabled
    and read-only while logically disabled, and paint the arrows ourselves.
    Enable(False) still blocks typing, paste, wheel and arrows and preserves the
    committed value. Only this control's surfaces are affected.
    """
    _integer = False

    def __init__(self, parent, id=wx.ID_ANY, value='', pos=wx.DefaultPosition,
                 size=wx.DefaultSize, style=wx.SP_ARROW_KEYS, min=0, max=100,
                 initial=0, inc=1, name='SpinCtrlDouble', **kwargs):
        super().__init__(parent, id, pos, size, style=wx.BORDER_NONE, name=name,
                         **kwargs)
        self._interactive = True
        self._minimum, self._maximum = float(min), float(max)
        self._increment = float(inc)
        self._digits = 0
        self._value = self._bounded(initial)
        self._style = style
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(WHITE)
        self.SetForegroundColour(TEXT)
        self._editor = wx.TextCtrl(self, style=wx.BORDER_NONE | wx.TE_PROCESS_ENTER)
        self._editor.SetBackgroundColour(WHITE)
        self._editor.SetForegroundColour(TEXT)
        self._editor.SetFont(self.GetFont())
        self._arrows = _SpinArrows(self)
        self._arrows.SetMinSize((self.FromDIP(18), -1))
        self._editor.Bind(wx.EVT_TEXT, self._edited)
        self._editor.Bind(wx.EVT_TEXT_ENTER, self._commit_event)
        self._editor.Bind(wx.EVT_KILL_FOCUS, self._commit_event)
        self._editor.Bind(wx.EVT_SET_FOCUS, self._focus)
        self._editor.Bind(wx.EVT_KEY_DOWN, self._key)
        self._editor.Bind(wx.EVT_CHAR, self._char)
        self._editor.Bind(wx.EVT_MOUSEWHEEL, self._wheel)
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_SIZE, self._layout)
        self.Bind(wx.EVT_SET_FOCUS, self._focus)
        self.Bind(wx.EVT_MOUSEWHEEL, self._wheel)
        self.SetMinSize((builtins.max(self.FromDIP(75), size[0]),
                         builtins.max(self.FromDIP(28), size[1])))
        if value:
            self.SetValue(value)
        else:
            self._display_value()
        self._layout()

    def DoGetBestSize(self):
        return wx.Size(self.FromDIP(100), self.FromDIP(28))

    def _bounded(self, value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('Numeric control value must be finite')
        return max(self._minimum, min(self._maximum, number))

    def _parsed(self):
        try:
            return self._bounded(self._editor.GetValue().strip().replace(',', '.'))
        except (ValueError, TypeError):
            return self._value

    def _display_value(self):
        self._editor.ChangeValue(format(self._value, f'.{self._digits}f'))

    def _layout(self, event=None):
        if hasattr(self, '_editor'):
            width, height = self.GetClientSize()
            arrow_width = self.FromDIP(18)
            text_height = min(max(1, height-4), self._editor.GetBestSize().height)
            self._editor.SetSize(self.FromDIP(5), max(2, (height-text_height)//2),
                                 max(1, width-arrow_width-self.FromDIP(10)), text_height)
            self._arrows.SetSize(max(1, width-arrow_width-1), 1,
                                 arrow_width, max(1, height-2))
        self.Refresh()
        if event:
            event.Skip()

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(WHITE if self.IsEnabled() else SOFT))
        dc.Clear()
        width, height = self.GetClientSize()
        focused = self._editor.HasFocus() and self.IsEnabled()
        dc.SetPen(wx.Pen(ACCENT if focused else LINE))
        dc.DrawLines([(0, 0), (width-1, 0), (width-1, height-1),
                      (0, height-1), (0, 0)])

    def _focus(self, event):
        if event.GetEventObject() is self and self.IsEnabled():
            self._editor.SetFocus()
        self.Refresh()
        event.Skip()

    def _emit_text(self):
        event = wx.CommandEvent(wx.EVT_TEXT.typeId, self.GetId())
        event.SetEventObject(self)
        event.SetString(self._editor.GetValue())
        self.GetEventHandler().ProcessEvent(event)

    def _edited(self, event):
        # Re-emit once with the public wrapper as event object, like a native
        # spin control, instead of exposing its internal text editor to callers.
        event.StopPropagation()
        if not self.IsEnabled():
            self._display_value()
            return
        self._value = self._parsed()
        self._emit_text()

    def _commit_event(self, event):
        if self.IsEnabled():
            self._value = self._parsed()
            self._display_value()
        self.Refresh()
        if event.GetEventType() == wx.EVT_KILL_FOCUS.typeId:
            event.Skip()

    def _step(self, direction):
        if not self.IsEnabled():
            return
        previous = self.GetValue()
        amount = direction*self._increment
        value = previous+amount
        if self._style & wx.SP_WRAP:
            if value > self._maximum:
                value = self._minimum
            elif value < self._minimum:
                value = self._maximum
        self.SetValue(value)
        if self.GetValue() == previous:
            return
        self._emit_text()
        if self._integer:
            event = wx.SpinEvent(wx.EVT_SPINCTRL.typeId, self.GetId())
            event.SetPosition(self.GetValue())
        else:
            event = wx.SpinDoubleEvent(wx.EVT_SPINCTRLDOUBLE.typeId, self.GetId(), self.GetValue())
        event.SetEventObject(self)
        self.GetEventHandler().ProcessEvent(event)

    def _key(self, event):
        key = event.GetKeyCode()
        if not self.IsEnabled():
            # Read-only text still permits copying and normal Tab navigation.
            if key == wx.WXK_TAB or (event.ControlDown() and key in (ord('C'), ord('A'))):
                event.Skip()
            return
        if key in (wx.WXK_UP, wx.WXK_DOWN) and self._style & wx.SP_ARROW_KEYS:
            self._step(1 if key == wx.WXK_UP else -1)
        else:
            event.Skip()

    def _char(self, event):
        if self.IsEnabled() or event.GetKeyCode() == wx.WXK_TAB:
            event.Skip()

    def _wheel(self, event):
        if self.IsEnabled() and self._editor.HasFocus():
            delta = event.GetWheelDelta()
            if delta:
                self._step(int(event.GetWheelRotation()/delta))
        # Never pass wheel events to the native editor while logically disabled.

    def GetValue(self):
        if self.IsEnabled():
            self._value = self._parsed()
        return int(round(self._value)) if self._integer else self._value

    def SetValue(self, value):
        self._value = self._bounded(value)
        self._display_value()

    def SetDigits(self, digits):
        self._digits = max(0, min(20, int(digits)))
        self._display_value()

    def GetDigits(self):
        return self._digits

    def SetRange(self, minimum, maximum):
        self._minimum, self._maximum = float(minimum), float(maximum)
        self.SetValue(self._value)

    def GetMin(self): return self._minimum
    def GetMax(self): return self._maximum
    def GetIncrement(self): return self._increment

    def SetIncrement(self, increment):
        self._increment = float(increment)

    def SetSelection(self, start, end):
        self._editor.SetSelection(start, end)

    def SetToolTip(self, tip):
        super().SetToolTip(tip)
        self._editor.SetToolTip(tip)
        self._arrows.SetToolTip(tip)

    def IsEnabled(self):
        return self._interactive and super().IsEnabled()

    def IsThisEnabled(self):
        return self._interactive and super().IsThisEnabled()

    def Enable(self, enable=True):
        enable = bool(enable)
        changed = enable != self._interactive
        if self._interactive and not enable:
            self._value = self._parsed()
            self._display_value()
        self._interactive = enable
        self._editor.SetEditable(enable)
        face = WHITE if enable else SOFT
        self.SetBackgroundColour(face)
        self._editor.SetBackgroundColour(face)
        self._editor.SetForegroundColour(TEXT if enable else MUTED)
        self._arrows.SetBackgroundColour(face)
        self.Refresh()
        self._editor.Refresh()
        self._arrows.Refresh()
        return changed

    def Disable(self):
        return self.Enable(False)


class LightSpinCtrl(LightSpinCtrlDouble):
    """Integer variant used for the mesh-cell budget."""
    _integer = True

    def __init__(self, parent, id=wx.ID_ANY, value='', pos=wx.DefaultPosition,
                 size=wx.DefaultSize, style=wx.SP_ARROW_KEYS, min=0, max=100,
                 initial=0, name='SpinCtrl', **kwargs):
        super().__init__(parent, id, value, pos, size, style, min, max, initial,
                         inc=1, name=name, **kwargs)


class _ChoiceRows(wx.VListBox):
    def __init__(self, parent, owner):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.owner = owner
        self.SetFont(owner.GetFont())
        self.SetBackgroundColour(WHITE)
        self.SetForegroundColour(TEXT)
        self.SetItemCount(owner.GetCount())
        self.SetSelection(owner.GetSelection())
        self.Bind(wx.EVT_LISTBOX, self._choose)
        self.Bind(wx.EVT_KEY_DOWN, self._key)

    def OnMeasureItem(self, index):
        return self.FromDIP(28)

    def OnDrawBackground(self, dc, rect, index):
        dc.SetPen(wx.Pen(WHITE, style=wx.PENSTYLE_TRANSPARENT))
        dc.SetBrush(wx.Brush(SELECTED if self.IsSelected(index) else WHITE))
        dc.DrawRectangle(rect)

    def OnDrawItem(self, dc, rect, index):
        dc.SetFont(self.GetFont())
        dc.SetTextForeground(TEXT)
        label = _text(dc, self.owner.GetString(index), rect.width - self.FromDIP(18))
        height = dc.GetTextExtent(label).height
        dc.DrawText(label, rect.x + self.FromDIP(8), rect.y + (rect.height-height)//2)

    def _choose(self, event):
        self.owner._choose(self.GetSelection())
        self.GetParent().Dismiss()

    def _key(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_ESCAPE:
            self.GetParent().Dismiss()
        elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_SPACE):
            self.owner._choose(self.GetSelection())
            self.GetParent().Dismiss()
        else:
            event.Skip()


class _ChoicePopup(wx.PopupTransientWindow):
    def __init__(self, owner):
        # wx.PopupTransientWindow calls this argument ``flags``, unlike most
        # controls' ``style``. Positional form supports KiCad's bundled wx.
        super().__init__(owner, wx.BORDER_SIMPLE)
        self.owner = owner
        self._closing = False
        self.rows = _ChoiceRows(self, owner)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.rows, 1, wx.EXPAND)
        self.SetSizer(sizer)
        width = max(owner.GetSize().width, owner.FromDIP(140))
        self.SetSize((width, owner.FromDIP(28 * min(12, max(1, owner.GetCount())) + 2)))

    def _closed(self):
        if self._closing:
            return
        self._closing = True
        if self.owner and self.owner._popup is self:
            self.owner._popup = None
            self.owner.Refresh()
        # Defer destruction until VListBox selection/key handlers have returned.
        wx.CallAfter(self._destroy)

    def _destroy(self):
        if self:
            self.Destroy()

    def Dismiss(self):
        # Native wx invokes OnDismiss only for automatic dismissal (outside
        # clicks), not when code calls Dismiss after selecting an item. Without
        # this cleanup every later click keeps dismissing an already hidden
        # popup instead of opening a new one.
        if self._closing:
            return
        super().Dismiss()
        self._closed()

    def OnDismiss(self):
        self._closed()


class LightChoice(wx.Control):
    """Read-only choice with an explicitly painted light face and popup.

    Programmatic SetSelection is quiet, matching wx.Choice. User selection emits
    wx.EVT_CHOICE with the selected index/string and this control as event object.
    """
    def __init__(self, parent, id=wx.ID_ANY, pos=wx.DefaultPosition,
                 size=wx.DefaultSize, choices=(), style=0, **kwargs):
        super().__init__(parent, id, pos, size, style=wx.BORDER_NONE | wx.WANTS_CHARS,
                         **kwargs)
        self._items = [str(item) for item in choices]
        self._selection = wx.NOT_FOUND
        self._popup = None
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(WHITE)
        self.SetForegroundColour(TEXT)
        self.SetMinSize((max(self.FromDIP(80), size[0]), max(self.FromDIP(28), size[1])))
        self.Bind(wx.EVT_PAINT, self._paint)
        # Open after the triggering mouse button is released. A transient
        # native popup must not inherit the original mouse-down/capture cycle.
        self.Bind(wx.EVT_LEFT_UP, self._open)
        self.Bind(wx.EVT_KEY_DOWN, self._key)
        self.Bind(wx.EVT_SET_FOCUS, self._focus)
        self.Bind(wx.EVT_KILL_FOCUS, self._focus)
        self.SetName('Choice')

    def DoGetBestSize(self):
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        longest = max((dc.GetTextExtent(item).width for item in self._items), default=60)
        return wx.Size(min(self.FromDIP(280), longest + self.FromDIP(36)), self.FromDIP(28))

    def _focus(self, event):
        self.Refresh()
        if event:
            event.Skip()

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        enabled = self.IsEnabled()
        dc.SetBackground(wx.Brush(WHITE if enabled else SOFT))
        dc.Clear()
        width, height = self.GetClientSize()
        dc.SetPen(wx.Pen(ACCENT if self.HasFocus() else LINE))
        # KiCad may mutate wx stock brushes. Stroke the border without using
        # wx.TRANSPARENT_BRUSH, which otherwise can fill over the control text.
        dc.DrawLines([(0, 0), (width-1, 0), (width-1, height-1),
                      (0, height-1), (0, 0)])
        dc.SetFont(self.GetFont())
        dc.SetTextForeground(TEXT if enabled else MUTED)
        label = _text(dc, self.GetStringSelection(), width-self.FromDIP(32))
        dc.DrawText(label, self.FromDIP(8), (height-dc.GetTextExtent(label).height)//2)
        x, y, d = width-self.FromDIP(14), height//2, self.FromDIP(4)
        dc.SetPen(wx.Pen(MUTED, 1))
        dc.DrawLines([(x-d, y-2), (x, y+2), (x+d, y-2)])

    def _open(self, event=None):
        if not self.IsEnabled() or not self._items:
            return
        self.SetFocus()
        if self._popup:
            self._popup.Dismiss()
            return
        self._popup = _ChoicePopup(self)
        self._popup.Position(self.ClientToScreen((0, self.GetClientSize().height)), (0, 0))
        self._popup.Popup(self._popup.rows)
        self.Refresh()

    def _choose(self, index):
        if not 0 <= index < len(self._items):
            return
        self.SetSelection(index)
        event = wx.CommandEvent(wx.EVT_CHOICE.typeId, self.GetId())
        event.SetEventObject(self)
        event.SetInt(index)
        event.SetString(self.GetStringSelection())
        self.GetEventHandler().ProcessEvent(event)

    def _key(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_SPACE, wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, wx.WXK_F4) or (event.AltDown() and key == wx.WXK_DOWN):
            self._open()
        elif key in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_HOME, wx.WXK_END):
            if self._items:
                index = (0 if key == wx.WXK_HOME else len(self._items)-1 if key == wx.WXK_END else
                         max(0, min(len(self._items)-1, self._selection + (1 if key == wx.WXK_DOWN else -1))))
                self._choose(index)
        else:
            event.Skip()

    def Set(self, items):
        if self._popup:
            self._popup.Dismiss()
        self._items = [str(item) for item in items]
        self._selection = wx.NOT_FOUND
        self.InvalidateBestSize()
        self.Refresh()

    SetItems = Set

    def GetItems(self):
        return list(self._items)

    def GetCount(self):
        return len(self._items)

    def GetString(self, index):
        return self._items[index]

    def SetString(self, index, value):
        self._items[index] = str(value)
        self.Refresh()

    def GetSelection(self):
        return self._selection

    def SetSelection(self, index):
        if index != wx.NOT_FOUND and not 0 <= index < len(self._items):
            raise IndexError('Choice selection is out of range')
        self._selection = index
        self.SetLabel(self.GetStringSelection())
        self.Refresh()

    def GetStringSelection(self):
        return self._items[self._selection] if 0 <= self._selection < len(self._items) else ''

    def FindString(self, value, caseSensitive=False):
        for index, item in enumerate(self._items):
            if item == value if caseSensitive else item.casefold() == str(value).casefold():
                return index
        return wx.NOT_FOUND

    def SetStringSelection(self, value):
        index = self.FindString(value)
        if index < 0:
            return False
        self.SetSelection(index)
        return True

    def Clear(self):
        self.Set([])

    def Append(self, value):
        if self._popup:
            self._popup.Dismiss()
        self._items.append(str(value))
        self.InvalidateBestSize()
        self.Refresh()
        return len(self._items)-1

    def Enable(self, enable=True):
        if not enable and self._popup:
            self._popup.Dismiss()
        changed = super().Enable(enable)
        self.Refresh()
        return changed


class _Tabs(wx.Control):
    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_NONE | wx.WANTS_CHARS)
        self.owner = parent
        self.rectangles = []
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._paint)
        self.Bind(wx.EVT_LEFT_DOWN, self._click)
        self.Bind(wx.EVT_KEY_DOWN, self._key)
        self.Bind(wx.EVT_SIZE, self._size)
        self.SetMinSize((-1, self.FromDIP(32)))

    def _positions(self):
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        width = max(self.FromDIP(80), self.GetClientSize().width)
        height = self.FromDIP(32)
        x = y = 0
        rectangles = []
        for label in self.owner._labels:
            item_width = min(width, dc.GetTextExtent(label).width + self.FromDIP(24))
            if x and x+item_width > width:
                x = 0
                y += height
            rectangles.append(wx.Rect(x, y, item_width, height))
            x += item_width
        return rectangles, y+height

    def _size(self, event=None):
        _, height = self._positions()
        if self.GetMinSize().height != height:
            self.SetMinSize((-1, height))
            wx.CallAfter(self.owner.Layout)
        self.Refresh()
        if event:
            event.Skip()

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(SOFT))
        dc.Clear()
        dc.SetFont(self.GetFont())
        self.rectangles, _ = self._positions()
        for index, rect in enumerate(self.rectangles):
            selected = index == self.owner.GetSelection()
            dc.SetPen(wx.Pen(LINE))
            dc.SetBrush(wx.Brush(WHITE if selected else SOFT))
            dc.DrawRectangle(rect)
            dc.SetTextForeground(ACCENT if selected else TEXT)
            label = _text(dc, self.owner._labels[index], rect.width-self.FromDIP(16))
            dc.DrawText(label, rect.x+self.FromDIP(8), rect.y+(rect.height-dc.GetTextExtent(label).height)//2)
            if selected:
                dc.SetPen(wx.Pen(ACCENT, self.FromDIP(3)))
                dc.DrawLine(rect.x+1, rect.bottom-2, rect.right-1, rect.bottom-2)

    def _click(self, event):
        self.SetFocus()
        rectangles, _ = self._positions()
        for index, rect in enumerate(rectangles):
            if rect.Contains(event.GetPosition()):
                self.owner.SetSelection(index)
                break

    def _key(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_LEFT, wx.WXK_RIGHT, wx.WXK_HOME, wx.WXK_END) and self.owner.GetPageCount():
            count = self.owner.GetPageCount()
            index = (0 if key == wx.WXK_HOME else count-1 if key == wx.WXK_END else
                     (self.owner.GetSelection() + (1 if key == wx.WXK_RIGHT else -1)) % count)
            self.owner.SetSelection(index)
        else:
            event.Skip()


class LightNotebook(wx.Panel):
    """Notebook with light, wrapping tabs rather than host-themed native tabs."""
    def __init__(self, parent, id=wx.ID_ANY, **kwargs):
        super().__init__(parent, id=id, **kwargs)
        self._labels = []
        self._tabs = _Tabs(self)
        self._book = wx.Simplebook(self)
        self.SetBackgroundColour(WHITE)
        self._book.SetBackgroundColour(WHITE)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._tabs, 0, wx.EXPAND)
        sizer.Add(self._book, 1, wx.EXPAND)
        self.SetSizer(sizer)

    def AddPage(self, page, text, select=False, imageId=-1):
        page.Reparent(self._book)
        result = self._book.AddPage(page, text, select)
        self._labels.append(str(text))
        self._tabs._size()
        return result

    def SetPageText(self, index, text):
        self._labels[index] = str(text)
        self._book.SetPageText(index, text)
        self._tabs._size()
        return True

    def GetPageText(self, index):
        return self._labels[index]

    def GetPageCount(self):
        return self._book.GetPageCount()

    def GetPage(self, index):
        return self._book.GetPage(index)

    def GetCurrentPage(self):
        return self._book.GetCurrentPage()

    def GetSelection(self):
        return self._book.GetSelection()

    def SetSelection(self, index):
        old = self.GetSelection()
        if old == index:
            return old
        changing = wx.BookCtrlEvent(wx.EVT_NOTEBOOK_PAGE_CHANGING.typeId, self.GetId(), index, old)
        changing.SetEventObject(self)
        self.GetEventHandler().ProcessEvent(changing)
        if not changing.IsAllowed():
            return old
        # The wrapper owns the public notebook event; Simplebook events use the
        # same wx event IDs and would otherwise bubble up as a duplicate.
        self._book.ChangeSelection(index)
        self._tabs.Refresh()
        changed = wx.BookCtrlEvent(wx.EVT_NOTEBOOK_PAGE_CHANGED.typeId, self.GetId(), index, old)
        changed.SetEventObject(self)
        self.GetEventHandler().ProcessEvent(changed)
        return old


class _ListHeader(wx.Control):
    def __init__(self, parent):
        super().__init__(parent, style=wx.BORDER_NONE)
        self.owner = parent
        self.SetMinSize((-1, self.FromDIP(30)))
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._paint)

    def _paint(self, event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(SOFT))
        dc.Clear()
        dc.SetFont(self.GetFont())
        dc.SetTextForeground(TEXT)
        dc.SetPen(wx.Pen(LINE))
        height = self.GetClientSize().height
        body = self.owner._body
        x = -body.GetScrollPos(wx.HORIZONTAL)
        for index in range(body.GetColumnCount()):
            width = body.GetColumnWidth(index)
            label = _text(dc, body.GetColumn(index).GetText(), width-self.FromDIP(14))
            dc.DrawText(label, x+self.FromDIP(7), (height-dc.GetTextExtent(label).height)//2)
            x += width
            dc.DrawLine(x-1, 0, x-1, height)
        dc.DrawLine(0, height-1, self.GetClientSize().width, height-1)


class LightListCtrl(wx.Panel):
    """Native report-list body with a separate, predictably light header.

    The forwarding methods intentionally cover the report-list API used by the
    terminal editor. Selection/activation remain real native wx.ListEvents.
    """
    def __init__(self, parent, id=wx.ID_ANY, style=0, **kwargs):
        super().__init__(parent, id=id, **kwargs)
        self._header = _ListHeader(self)
        self._body = wx.ListCtrl(self, style=(style & ~wx.BORDER_MASK) |
                                 wx.LC_REPORT | wx.LC_NO_HEADER | wx.BORDER_NONE)
        self._body.SetBackgroundColour(WHITE)
        self._body.SetTextColour(TEXT)
        self.SetBackgroundColour(WHITE)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._header, 0, wx.EXPAND)
        sizer.Add(self._body, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self._body.Bind(wx.EVT_SCROLLWIN, self._scroll)

    def _scroll(self, event):
        self._header.Refresh()
        event.Skip()

    def Bind(self, event, handler, *args, **kwargs):
        if hasattr(self, '_body') and event.typeId in {
                wx.EVT_LIST_ITEM_SELECTED.typeId, wx.EVT_LIST_ITEM_DESELECTED.typeId,
                wx.EVT_LIST_ITEM_ACTIVATED.typeId, wx.EVT_LIST_ITEM_FOCUSED.typeId}:
            return self._body.Bind(event, handler, *args, **kwargs)
        return super().Bind(event, handler, *args, **kwargs)

    def InsertColumn(self, *args, **kwargs):
        value = self._body.InsertColumn(*args, **kwargs)
        self._header.Refresh()
        return value

    def SetColumn(self, *args, **kwargs):
        value = self._body.SetColumn(*args, **kwargs)
        self._header.Refresh()
        return value

    def SetColumnWidth(self, *args, **kwargs):
        value = self._body.SetColumnWidth(*args, **kwargs)
        self._header.Refresh()
        return value

    def GetColumnCount(self): return self._body.GetColumnCount()
    def GetColumn(self, index): return self._body.GetColumn(index)
    def GetColumnWidth(self, index): return self._body.GetColumnWidth(index)
    def DeleteAllItems(self): return self._body.DeleteAllItems()
    def InsertItem(self, *args, **kwargs): return self._body.InsertItem(*args, **kwargs)
    def SetItem(self, *args, **kwargs): return self._body.SetItem(*args, **kwargs)
    def GetItem(self, *args, **kwargs): return self._body.GetItem(*args, **kwargs)
    def GetItemText(self, *args, **kwargs): return self._body.GetItemText(*args, **kwargs)
    def GetItemCount(self): return self._body.GetItemCount()
    def GetFirstSelected(self): return self._body.GetFirstSelected()
    def GetNextSelected(self, item): return self._body.GetNextSelected(item)
    def Select(self, *args, **kwargs): return self._body.Select(*args, **kwargs)
    def Focus(self, item): return self._body.Focus(item)
    def EnsureVisible(self, item): return self._body.EnsureVisible(item)
    def SetTextColour(self, colour): return self._body.SetTextColour(colour)
