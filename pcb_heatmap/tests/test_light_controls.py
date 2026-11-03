"""Local widgets retain selection/event APIs without host-native dark chrome."""
import unittest
from types import SimpleNamespace

import wx

from pcb_heatmap.ui_controls import (LightChoice, LightListCtrl, LightNotebook,
                                   LightSpinCtrl, LightSpinCtrlDouble, SOFT, WHITE)


class LightControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = wx.GetApp() or wx.App(False)

    def setUp(self):
        self.frame = wx.Frame(None, size=(600, 450))

    def tearDown(self):
        self.frame.Destroy()
        wx.Yield()

    def test_choice_quiet_set_and_user_event(self):
        choice = LightChoice(self.frame, choices=['F.Cu', 'In1.Cu', 'B.Cu'])
        events = []
        choice.Bind(wx.EVT_CHOICE, lambda e: events.append((e.GetInt(), e.GetString(), e.GetEventObject())))
        choice.SetSelection(1)
        self.assertEqual(events, [])
        self.assertEqual(choice.GetStringSelection(), 'In1.Cu')
        choice._choose(2)
        self.assertEqual(events, [(2, 'B.Cu', choice)])
        choice.SetString(2, 'Alt')
        self.assertEqual(choice.GetStringSelection(), 'Alt')
        self.assertTrue(choice.SetStringSelection('f.cu'))
        self.assertEqual(choice.GetSelection(), 0)
        choice.SetItems(['English', 'Türkçe'])
        self.assertEqual(choice.GetSelection(), wx.NOT_FOUND)
        self.assertEqual(choice.GetCount(), 2)
        choice.Append('Extra')
        self.assertEqual(choice.GetCount(), 3)
        choice.Clear()
        self.assertEqual(choice.GetItems(), [])

    def test_notebook_pages_events_and_turkish_wrap(self):
        book = LightNotebook(self.frame, size=(260, 300))
        for label in ('Girişler ve yükler', 'Hesap ayarları', 'Model notları'):
            book.AddPage(wx.Panel(book), label)
        events = []
        book.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED,
                  lambda e: events.append((e.GetSelection(), e.GetOldSelection())))
        self.assertEqual(book.SetSelection(2), 0)
        self.assertEqual(events, [(2, 0)])
        self.assertEqual(book.GetCurrentPage(), book.GetPage(2))
        book.SetPageText(2, 'Değişen model notları')
        self.assertEqual(book.GetPageText(2), 'Değişen model notları')
        book._tabs.SetSize((260, 32))
        rectangles, height = book._tabs._positions()
        self.assertGreater(height, book.FromDIP(32))
        self.assertEqual(len(rectangles), 3)
        self.assertTrue(all(rect.right <= 260 for rect in rectangles))

    def test_mouse_and_keyboard_open_real_popup_and_commit_selection(self):
        choice = LightChoice(self.frame, choices=['F.Cu', 'In1.Cu', 'B.Cu'],
                             pos=(10, 10), size=(260, 28))
        choice.SetSelection(0)
        self.frame.Show()
        wx.Yield()
        mouse = wx.MouseEvent(wx.wxEVT_LEFT_UP)
        mouse.SetPosition((15, 15))
        choice.GetEventHandler().ProcessEvent(mouse)
        wx.Yield()
        popup = choice._popup
        self.assertIsNotNone(popup)
        self.assertTrue(popup.IsShown())
        self.assertGreater(popup.GetSize().height, 28)
        self.assertEqual(popup.rows.GetItemCount(), 3)
        popup.rows.SetSelection(2)
        popup.rows._choose(wx.CommandEvent())
        wx.Yield()
        self.assertEqual(choice.GetStringSelection(), 'B.Cu')
        self.assertIsNone(choice._popup)
        choice._key(SimpleNamespace(GetKeyCode=lambda: wx.WXK_DOWN,
                                    AltDown=lambda: True))
        wx.Yield()
        self.assertIsNotNone(choice._popup)
        self.assertTrue(choice._popup.IsShown())
        choice._popup.Dismiss()
        wx.Yield()
        self.assertIsNone(choice._popup)

    def test_choice_visible_popup_mouse_and_repeated_selection(self):
        choice = LightChoice(self.frame, choices=['F.Cu', 'In1.Cu', 'B.Cu'], size=(240, 32))
        choice.SetSelection(0)
        events = []
        choice.Bind(wx.EVT_CHOICE, lambda event: events.append((event.GetInt(), event.GetString())))
        self.frame.Show()
        wx.Yield()
        # Exercise the bound mouse handler, rather than calling only _choose.
        down = wx.MouseEvent(wx.wxEVT_LEFT_DOWN)
        down.SetPosition((20, 12))
        choice.GetEventHandler().ProcessEvent(down)
        self.assertIsNone(choice._popup, 'The popup opens on release, not mouse-down.')
        up = wx.MouseEvent(wx.wxEVT_LEFT_UP)
        up.SetPosition((20, 12))
        choice.GetEventHandler().ProcessEvent(up)
        wx.Yield()
        self.assertIsNotNone(choice._popup)
        self.assertTrue(choice._popup.IsShown())
        rows = choice._popup.rows
        rows.SetSelection(2)
        selected = wx.CommandEvent(wx.EVT_LISTBOX.typeId, rows.GetId())
        selected.SetEventObject(rows)
        selected.SetInt(2)
        rows.GetEventHandler().ProcessEvent(selected)
        self.assertEqual(events, [(2, 'B.Cu')])
        self.assertIsNone(choice._popup, 'Programmatic row dismissal must release the popup.')
        wx.Yield()
        # Reopening used to repeatedly dismiss the same hidden popup forever.
        choice.GetEventHandler().ProcessEvent(up)
        wx.Yield()
        self.assertTrue(choice._popup.IsShown())
        choice._popup.Dismiss()
        wx.Yield()
        self.assertIsNone(choice._popup)
        key = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
        key.SetKeyCode(wx.WXK_F4)
        choice.GetEventHandler().ProcessEvent(key)
        wx.Yield()
        self.assertTrue(choice._popup.IsShown())
        choice.Enable(False)
        wx.Yield()
        self.assertIsNone(choice._popup)
        choice.Enable(True)
        choice._open()
        wx.Yield()
        self.assertTrue(choice._popup.IsShown())
        choice.SetItems(['English', 'Türkçe'])
        wx.Yield()
        self.assertIsNone(choice._popup)
        self.assertEqual(choice.GetItems(), ['English', 'Türkçe'])

    def test_list_header_and_real_row_events(self):
        report = LightListCtrl(self.frame, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SIMPLE)
        for label in ('Tür', 'Nokta / grup', 'Toplam'):
            report.InsertColumn(report.GetColumnCount(), label, width=110)
        item = report.GetColumn(1)
        item.SetText('Contact / group')
        report.SetColumn(1, item)
        self.assertEqual(report.GetColumn(1).GetText(), 'Contact / group')
        row = report.InsertItem(report.GetItemCount(), 'V')
        report.SetItem(row, 1, 'J8.2')
        report.SetItem(row, 2, '33.6 V')
        self.assertEqual(report.GetItemText(0, 2), '33.6 V')
        events = []
        report.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda e: events.append(e.GetIndex()))
        report.Select(0)
        self.assertEqual(report.GetFirstSelected(), 0)
        self.assertEqual(events, [0])
        self.assertTrue(report._body.GetWindowStyle() & wx.LC_NO_HEADER)
        report.DeleteAllItems()
        self.assertEqual(report.GetItemCount(), 0)

    def test_numeric_busy_keeps_every_child_light_and_blocks_user_changes(self):
        number = LightSpinCtrlDouble(self.frame, min=.025, max=2,
                                     initial=.25, inc=.025, size=(100, 28))
        number.SetDigits(3)
        self.frame.Show()
        wx.Yield()
        events = []
        number.Bind(wx.EVT_SPINCTRLDOUBLE, lambda e: events.append(e.GetValue()))
        self.assertTrue(number.Enable(False))
        wx.Yield()
        self.assertFalse(number.IsEnabled())
        self.assertFalse(number.IsThisEnabled())
        self.assertTrue(number._editor.IsEnabled(), 'Avoid host-native disabled edit rendering.')
        self.assertFalse(number._editor.IsEditable())
        for child in (number, number._editor, number._arrows):
            self.assertEqual(child.GetBackgroundColour(), wx.Colour(SOFT))
        # Exercise the actual bound key, wheel and arrow handlers while busy.
        key = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
        key.SetKeyCode(wx.WXK_UP)
        number._editor.GetEventHandler().ProcessEvent(key)
        click = wx.MouseEvent(wx.wxEVT_LEFT_DOWN)
        click.SetPosition((5, 2))
        number._arrows.GetEventHandler().ProcessEvent(click)
        wheel = SimpleNamespace(GetWheelDelta=lambda: 120, GetWheelRotation=lambda: 120)
        number._wheel(wheel)
        self.assertEqual(number.GetValue(), .25)
        self.assertEqual(number._editor.GetValue(), '0.250')
        self.assertEqual(events, [])
        self.assertFalse(number.Enable(False), 'Repeated busy updates are idempotent.')
        self.assertTrue(number.Enable(True))
        self.assertTrue(number.IsEnabled())
        self.assertTrue(number._editor.IsEditable())
        self.assertEqual(number._editor.GetBackgroundColour(), wx.Colour(WHITE))
        number._editor.GetEventHandler().ProcessEvent(key)
        self.assertAlmostEqual(number.GetValue(), .275)
        self.assertEqual(events, [.275])

    def test_numeric_text_commits_ranges_integer_events_and_quiet_setters(self):
        number = LightSpinCtrlDouble(self.frame, min=-40, max=150,
                                     initial=25, inc=.5)
        number.SetDigits(1)
        events = []
        number.Bind(wx.EVT_TEXT, lambda e: events.append((e.GetEventObject(), e.GetString())))
        number.SetValue(30)
        self.assertEqual(events, [])
        number._editor.SetValue('12,5')
        self.assertEqual(number.GetValue(), 12.5)
        self.assertEqual(events, [(number, '12,5')])
        number._editor.SetValue('-')
        self.assertEqual(number.GetValue(), 12.5)
        number.Disable()
        self.assertEqual(number._editor.GetValue(), '12.5')
        number.SetValue(500)
        self.assertEqual(number.GetValue(), 150)
        number.SetRange(0, 100)
        self.assertEqual(number.GetValue(), 100)
        number.Enable()
        number._editor.SetValue('nan')
        self.assertEqual(number.GetValue(), 100)
        number._commit_event(wx.FocusEvent(wx.wxEVT_KILL_FOCUS))
        self.assertEqual(number._editor.GetValue(), '100.0')
        budget = LightSpinCtrl(self.frame, min=10000, max=2000000, initial=500000)
        spins = []
        budget.Bind(wx.EVT_SPINCTRL, lambda e: spins.append((e.GetPosition(), e.GetEventObject())))
        budget._step(1)
        self.assertIsInstance(budget.GetValue(), int)
        self.assertEqual(budget.GetValue(), 500001)
        self.assertEqual(spins, [(500001, budget)])
        budget.Disable()
        budget._step(1)
        self.assertEqual(budget.GetValue(), 500001)
        budget.Enable()
        budget._step(-1)
        self.assertEqual(budget.GetValue(), 500000)


if __name__ == '__main__':
    unittest.main()
