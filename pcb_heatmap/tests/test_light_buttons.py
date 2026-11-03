"""Input, dialog and painting regressions for locally themed command controls."""
import unittest

import wx

from pcb_heatmap.ui_controls import (
    LightButton, LightCheckBox, LightCheckListBox, LightToggleButton, SOFT, WHITE,
)


class SimulatedKeyEvent(wx.KeyEvent):
    """Give injected keys the repeat state that native Windows events supply.

    wxWidgets 3.2.6's wxKeyEvent(type) constructor leaves m_isRepeat uninitialized
    (src/common/event.cpp); wxPython 4.2.2 exposes no setter for that field.
    A real OS key event initializes it, but test-created events can randomly
    look like repeats. Keep the production repeat check exercised explicitly.
    """
    def __init__(self, kind, repeat=False):
        super().__init__(kind)
        self._repeat = repeat

    def IsAutoRepeat(self):
        return self._repeat


class LightButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        self.frame = wx.Frame(None, size=(480, 240))
        self.frame.Show()
        wx.Yield()

    def tearDown(self):
        self.frame.Destroy()
        wx.Yield()

    @staticmethod
    def mouse(control, kind, position):
        event = wx.MouseEvent(kind)
        event.SetPosition(position)
        control.GetEventHandler().ProcessEvent(event)

    @staticmethod
    def key(control, kind, code, alt=False, repeat=False):
        event = SimulatedKeyEvent(kind, repeat=repeat)
        event.SetKeyCode(code)
        event.SetAltDown(alt)
        control.GetEventHandler().ProcessEvent(event)

    @staticmethod
    def rendered(control):
        size = control.GetClientSize()
        bitmap = wx.Bitmap(max(1, size.width), max(1, size.height))
        dc = wx.MemoryDC(bitmap)
        control._draw(dc)
        dc.SelectObject(wx.NullBitmap)
        return bitmap.ConvertToImage()

    def test_commands_bubble_with_id_control_and_checked_state(self):
        cases = ((LightButton, wx.EVT_BUTTON),
                 (LightToggleButton, wx.EVT_TOGGLEBUTTON),
                 (LightCheckBox, wx.EVT_CHECKBOX))
        for control_type, command_type in cases:
            with self.subTest(control=control_type.__name__):
                control = control_type(self.frame, label='Türkçe işlem', size=(200, 32))
                received = []
                self.frame.Bind(command_type, lambda event: received.append(
                    (event.GetId(), event.GetEventObject(), event.GetInt())), id=control.GetId())
                if control_type is not LightButton:
                    control.SetValue(True)
                    self.assertEqual(received, [], 'SetValue must remain quiet.')
                    control.SetValue(False)
                self.mouse(control, wx.wxEVT_LEFT_DOWN, (10, 10))
                self.mouse(control, wx.wxEVT_LEFT_UP, (10, 10))
                self.assertEqual(len(received), 1)
                self.assertEqual(received[0][:2], (control.GetId(), control))
                if control_type is not LightButton:
                    self.assertEqual(received[0][2], 1)
                    self.assertTrue(control.GetValue())

    def test_drag_release_outside_and_lost_capture_do_not_click(self):
        button = LightButton(self.frame, label='Run', size=(150, 32))
        clicks = []
        button.Bind(wx.EVT_BUTTON, lambda event: clicks.append(event.GetId()))
        self.mouse(button, wx.wxEVT_LEFT_UP, (10, 10))
        self.mouse(button, wx.wxEVT_LEFT_DOWN, (10, 10))
        self.assertTrue(button.HasCapture())
        self.mouse(button, wx.wxEVT_MOTION, (200, 10))
        self.mouse(button, wx.wxEVT_LEFT_UP, (200, 10))
        self.assertFalse(button.HasCapture())
        self.assertEqual(clicks, [])
        self.mouse(button, wx.wxEVT_LEFT_DOWN, (10, 10))
        button.ReleaseMouse()
        button.GetEventHandler().ProcessEvent(wx.MouseCaptureLostEvent(button.GetId()))
        self.mouse(button, wx.wxEVT_LEFT_UP, (10, 10))
        self.assertEqual(clicks, [])
        # Re-entering during a deliberate drag still permits the usual release.
        self.mouse(button, wx.wxEVT_LEFT_DOWN, (10, 10))
        self.mouse(button, wx.wxEVT_MOTION, (200, 10))
        self.mouse(button, wx.wxEVT_MOTION, (10, 10))
        self.mouse(button, wx.wxEVT_LEFT_UP, (10, 10))
        self.assertEqual(clicks, [button.GetId()])

    def test_space_repeats_once_and_disabling_cancels_pending_click(self):
        checkbox = LightCheckBox(self.frame, label='Show tracks', size=(200, 32))
        changes = []
        checkbox.Bind(wx.EVT_CHECKBOX, lambda event: changes.append(event.IsChecked()))
        checkbox.SetFocus()
        for _ in range(3):
            self.key(checkbox, wx.wxEVT_KEY_DOWN, wx.WXK_SPACE)
        self.assertFalse(checkbox.GetValue())
        self.key(checkbox, wx.wxEVT_KEY_UP, wx.WXK_SPACE)
        self.assertTrue(checkbox.IsChecked())
        self.assertEqual(changes, [True])
        self.key(checkbox, wx.wxEVT_KEY_DOWN, wx.WXK_SPACE)
        checkbox.Disable()
        self.key(checkbox, wx.wxEVT_KEY_UP, wx.WXK_SPACE)
        self.mouse(checkbox, wx.wxEVT_LEFT_DOWN, (10, 10))
        self.mouse(checkbox, wx.wxEVT_LEFT_UP, (10, 10))
        self.assertEqual(changes, [True])
        self.assertFalse(checkbox.HasCapture())
        checkbox.Enable()
        self.key(checkbox, wx.wxEVT_KEY_DOWN, wx.WXK_SPACE)
        self.key(checkbox, wx.wxEVT_KEY_UP, wx.WXK_SPACE)
        self.assertEqual(changes, [True, False])

    def test_unchecked_square_is_light_at_rest_hover_focus_and_disabled(self):
        checkbox = LightCheckBox(self.frame, label='Pad numbers', size=(220, 32))
        for state in ('rest', 'hover', 'pressed', 'disabled'):
            with self.subTest(state=state):
                checkbox.Enable(state != 'disabled')
                checkbox.SetValue(False)
                checkbox._hovered = state in ('hover', 'pressed')
                checkbox._mouse_pressed = state == 'pressed'
                if state != 'disabled':
                    checkbox.SetFocus()
                image = self.rendered(checkbox)
                x, y = 7, 16
                expected = wx.Colour(SOFT if state == 'disabled' else WHITE)
                self.assertEqual((image.GetRed(x, y), image.GetGreen(x, y), image.GetBlue(x, y)),
                                 (expected.Red(), expected.Green(), expected.Blue()))

    def test_button_faces_stay_light_for_every_interaction_state(self):
        for control_type in (LightButton, LightToggleButton):
            control = control_type(self.frame, label='Run analysis', size=(200, 32))
            for state in ('rest', 'hover', 'pressed', 'selected', 'disabled'):
                with self.subTest(control=control_type.__name__, state=state):
                    control.Enable(state != 'disabled')
                    control._hovered = state in ('hover', 'pressed')
                    control._mouse_pressed = state == 'pressed'
                    if isinstance(control, LightToggleButton):
                        control.SetValue(state == 'selected')
                    image = self.rendered(control)
                    pixel = tuple(getter(7, 7) for getter in
                                  (image.GetRed, image.GetGreen, image.GetBlue))
                    self.assertGreater(min(pixel), 210, 'Host dark colours must never paint the face.')

    def test_default_enter_and_stock_buttons_close_modal_dialogs(self):
        for requested_id, use_enter, check_focus in ((wx.ID_OK, True, False),
                                                    (wx.ID_OK, True, True),
                                                    (wx.ID_CANCEL, False, False)):
            with self.subTest(id=requested_id):
                dialog = wx.Dialog(self.frame)
                editor = wx.TextCtrl(dialog, pos=(5, 5), size=(140, 24))
                button = LightButton(dialog, requested_id, pos=(5, 40))
                checkbox = LightCheckBox(dialog, label='Show tracks', pos=(150, 5))
                if use_enter:
                    button.SetDefault()
                    self.assertIs(dialog.GetDefaultItem(), button)
                timed_out = []
                ready = wx.Timer(dialog)
                def finish(event):
                    # A queued CallAfter can run before a hosted Windows
                    # runner has displayed and focused the modal window.
                    # Inject Enter only once the same preconditions as real
                    # keyboard input are satisfied; the guard still fails if
                    # the dialog or its focus never becomes ready.
                    target = checkbox if check_focus else editor
                    if not dialog.IsShownOnScreen() or not button.IsShownOnScreen():
                        return
                    target.SetFocus()
                    if wx.Window.FindFocus() is not target:
                        return
                    ready.Stop()
                    if use_enter:
                        self.key(dialog, wx.wxEVT_CHAR_HOOK, wx.WXK_RETURN)
                    else:
                        button._activate()
                def timeout():
                    timed_out.append(True)
                    if dialog and dialog.IsModal():
                        dialog.EndModal(wx.ID_ABORT)
                guard = wx.CallLater(5000, timeout)
                dialog.Bind(wx.EVT_TIMER, finish, ready)
                ready.Start(10)
                result = dialog.ShowModal()
                ready.Stop()
                guard.Stop()
                dialog.Destroy()
                wx.Yield()
                self.assertEqual(timed_out, [])
                self.assertEqual(result, requested_id)

    def test_default_does_not_override_text_enter_handlers_or_disabled_button(self):
        dialog = wx.Dialog(self.frame, size=(320, 180))
        editor = wx.TextCtrl(dialog, style=wx.TE_PROCESS_ENTER)
        button = LightButton(dialog, wx.ID_OK)
        button.SetDefault()
        clicks = []
        button.Bind(wx.EVT_BUTTON, lambda event: clicks.append(True))
        dialog.Show()
        editor.SetFocus()
        wx.Yield()
        self.key(dialog, wx.wxEVT_CHAR_HOOK, wx.WXK_RETURN)
        self.assertEqual(clicks, [])
        button.Disable()
        button._activate()
        self.assertEqual(clicks, [])
        dialog.Destroy()
        wx.Yield()

    def test_mnemonic_and_label_size(self):
        checkbox = LightCheckBox(self.frame, label='&Tracks')
        small = checkbox.GetBestSize().width
        checkbox.SetLabel('&Bakır dolgular ve görünürlük ayarları')
        self.assertGreater(checkbox.GetBestSize().width, small)
        self.assertEqual(checkbox.GetLabelText(), 'Bakır dolgular ve görünürlük ayarları')
        self.key(self.frame, wx.wxEVT_CHAR_HOOK, ord('B'), alt=True)
        self.assertTrue(checkbox.GetValue())
        self.assertEqual(LightButton(self.frame, wx.ID_OK).GetLabelText(), 'OK')

    def test_checklist_quiet_setters_mouse_keyboard_and_filter_reset(self):
        checklist = LightCheckListBox(self.frame, choices=['J1.1 | GND', 'J1.2 | VCC'], size=(300, 100))
        received = []
        checklist.Bind(wx.EVT_CHECKLISTBOX, lambda event: received.append(
            (event.GetInt(), event.GetString(), event.GetEventObject())))
        checklist.Check(1)
        self.assertTrue(checklist.IsChecked(1))
        self.assertEqual(received, [])
        self.mouse(checklist, wx.wxEVT_LEFT_UP, (10, 10))
        self.assertEqual(received, [(0, 'J1.1 | GND', checklist)])
        self.assertTrue(checklist.IsChecked(0))
        self.key(checklist, wx.wxEVT_KEY_DOWN, wx.WXK_SPACE, repeat=True)
        self.assertTrue(checklist.IsChecked(0), 'Repeated Space must not toggle the row.')
        self.assertEqual(len(received), 1)
        self.key(checklist, wx.wxEVT_KEY_DOWN, wx.WXK_SPACE)
        self.assertFalse(checklist.IsChecked(0))
        self.assertEqual(len(received), 2)
        checklist.Disable()
        self.mouse(checklist, wx.wxEVT_LEFT_UP, (10, 10))
        self.key(checklist, wx.wxEVT_KEY_DOWN, wx.WXK_SPACE)
        self.assertEqual(len(received), 2)
        checklist.Set(['Filtered pad'])
        self.assertEqual(checklist.GetItems(), ['Filtered pad'])
        self.assertEqual(checklist.GetCount(), 1)
        self.assertFalse(checklist.IsChecked(0))
        self.assertEqual(checklist.GetSelection(), wx.NOT_FOUND)
        with self.assertRaises(IndexError):
            checklist.Check(1)

    def test_checklist_unchecked_square_paints_light_in_selected_and_disabled_rows(self):
        checklist = LightCheckListBox(self.frame, choices=['Pad one'], size=(250, 100))
        checklist.SetSelection(0)
        for enabled in (True, False):
            checklist.Enable(enabled)
            bitmap = wx.Bitmap(250, 32)
            dc = wx.MemoryDC(bitmap)
            rect = wx.Rect(0, 0, 250, 32)
            checklist.OnDrawBackground(dc, rect, 0)
            checklist.OnDrawItem(dc, rect, 0)
            dc.SelectObject(wx.NullBitmap)
            image = bitmap.ConvertToImage()
            pixel = (image.GetRed(12, 16), image.GetGreen(12, 16), image.GetBlue(12, 16))
            self.assertGreater(min(pixel), 210)


if __name__ == '__main__':
    unittest.main()
