# -*- coding: utf-8 -*-
"""输入光标跟随的数据采集：前台插入符、焦点控件与 IME 候选区域。"""
import ctypes
import ctypes.wintypes as wintypes
from collections import namedtuple

from PySide6.QtWidgets import QApplication

from . import debuglog, ime, probe, uia, winapi


InputContext = namedtuple("InputContext", "caret focus candidate screen")


def query_input_context():
    """Return the foreground caret and exclusion rectangles, or None on failure.

    每次调用都向 probe 记录一份诊断摘要（路径、耗时、结果），供日志与菜单复制。"""
    diag = {"result": "fail", "caret_source": "none", "candidate_source": "none"}
    with probe.Timer() as total:
        context = _query(diag)
    diag["total_ms"] = total.ms
    diag.update(ime.take_probe_info())
    if context is not None:
        diag["result"] = "ok"
        diag["caret"] = _rect_tuple(context.caret)
        diag["candidate"] = _rect_tuple(context.candidate)
    probe.record_query(**diag)
    return context


def _rect_tuple(rect):
    return None if rect is None else (rect.x(), rect.y(), rect.width(), rect.height())


def _query(diag):
    if not winapi.configure():
        diag["reason"] = "winapi unavailable"
        return None
    try:
        user32 = ctypes.windll.user32
        foreground = user32.GetForegroundWindow()
        if not foreground:
            diag["reason"] = "no foreground window"
            return None
        process_id = wintypes.DWORD()
        thread_id = user32.GetWindowThreadProcessId(
            foreground, ctypes.byref(process_id))
        if not thread_id:
            diag["reason"] = "no thread for foreground"
            return None
        diag["process"] = winapi.process_name(process_id.value)

        info = winapi.GUITHREADINFO()
        info.cbSize = ctypes.sizeof(winapi.GUITHREADINFO)
        with probe.Timer() as t:
            has_gui_info = bool(user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)))
        diag["gui_ms"] = t.ms
        if has_gui_info and info.hwndCaret:
            caret = winapi.client_rect_to_screen(info.hwndCaret, info.rcCaret)
            focus = winapi.window_rect(info.hwndFocus or info.hwndCaret)
            diag["caret_source"] = "guithreadinfo"
        else:
            with probe.Timer() as t:
                caret, focus = uia.input_rects()
            diag["uia_caret_ms"] = t.ms
            diag["caret_source"] = "uia" if caret is not None else "none"
        if caret is None:
            diag["reason"] = "no caret"
            return None
        ime_hwnd = (info.hwndFocus or info.hwndCaret) if has_gui_info else foreground
        excluded_hwnds = (foreground, info.hwndFocus, info.hwndCaret)
        candidate = ime.candidate_rect(caret, ime_hwnd, excluded_hwnds, foreground)
        screen_obj = QApplication.screenAt(caret.center()) or QApplication.primaryScreen()
        if screen_obj is None:
            diag["reason"] = "no screen"
            return None
        return InputContext(caret, focus, candidate, screen_obj.availableGeometry())
    except Exception:
        diag["reason"] = "exception"
        debuglog.exception('query_input_context')
        return None
