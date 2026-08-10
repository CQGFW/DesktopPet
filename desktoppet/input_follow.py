# -*- coding: utf-8 -*-
"""输入光标跟随的数据采集：前台插入符、焦点控件与 IME 候选区域。"""
import ctypes
import ctypes.wintypes as wintypes
from collections import namedtuple

from PySide6.QtWidgets import QApplication

from . import debuglog, ime, uia, winapi


InputContext = namedtuple("InputContext", "caret focus candidate screen")


def query_input_context():
    """Return the foreground caret and exclusion rectangles, or None on failure."""
    if not winapi.configure():
        return None
    try:
        user32 = ctypes.windll.user32
        foreground = user32.GetForegroundWindow()
        if not foreground:
            return None
        process_id = wintypes.DWORD()
        thread_id = user32.GetWindowThreadProcessId(
            foreground, ctypes.byref(process_id))
        if not thread_id:
            return None

        info = winapi.GUITHREADINFO()
        info.cbSize = ctypes.sizeof(winapi.GUITHREADINFO)
        has_gui_info = bool(user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)))
        if has_gui_info and info.hwndCaret:
            caret = winapi.client_rect_to_screen(info.hwndCaret, info.rcCaret)
            focus = winapi.window_rect(info.hwndFocus or info.hwndCaret)
        else:
            caret, focus = uia.input_rects()
        if caret is None:
            return None
        ime_hwnd = (info.hwndFocus or info.hwndCaret) if has_gui_info else foreground
        excluded_hwnds = (foreground, info.hwndFocus, info.hwndCaret)
        candidate = ime.candidate_rect(caret, ime_hwnd, excluded_hwnds, foreground)
        screen_obj = QApplication.screenAt(caret.center()) or QApplication.primaryScreen()
        if screen_obj is None:
            return None
        return InputContext(caret, focus, candidate, screen_obj.availableGeometry())
    except Exception:
        debuglog.exception('query_input_context')
        return None
