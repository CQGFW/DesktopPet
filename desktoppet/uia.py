# -*- coding: utf-8 -*-
"""UI Automation 客户端：按 vtable 偏移直接调 COM，免去 comtypes 依赖。

两个用途：前台应用不暴露 HWND 插入符时读取焦点文本范围（input_rects），
以及探测已渲染但没有可用窗口的 IME 候选条（candidate_rect）。"""
import ctypes
import ctypes.wintypes as wintypes
import sys
import uuid

from PySide6.QtCore import QRect

from . import debuglog, placement

UIA_TEXT_PATTERN_ID = 10014
COINIT_APARTMENTTHREADED = 0x2
RPC_E_CHANGED_MODE = -2147417850     # 0x80010106
_UIA_CLIENT = None
_COM_OWNED = False                   # CoInitializeEx 是否由本模块配对持有


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


class UIARECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_double),
                ("top", ctypes.c_double),
                ("width", ctypes.c_double),
                ("height", ctypes.c_double)]

_CLSID_CUIAUTOMATION = GUID.parse("ff48dba4-60ef-4201-aa87-54103eef594e")
_IID_IUIAUTOMATION = GUID.parse("30cbe57d-d9d0-452a-ab13-7ac5ac4825ee")
_IID_TEXT_PATTERN = GUID.parse("32e215ea-9c15-4268-8173-ee0c0eaf366c")


def com_vtable(pointer):
    return ctypes.cast(
        pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents


def com_release(pointer):
    if pointer:
        release = ctypes.WINFUNCTYPE(
            wintypes.ULONG, ctypes.c_void_p)(com_vtable(pointer)[2])
        release(pointer)


def client():
    """Create the process-local UI Automation client lazily on the GUI thread."""
    global _UIA_CLIENT, _COM_OWNED
    if _UIA_CLIENT:
        return _UIA_CLIENT
    if sys.platform != "win32":
        return None
    try:
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx.restype = ctypes.c_long
        hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        # S_OK / S_FALSE 表示本次调用需要配对的 CoUninitialize；
        # RPC_E_CHANGED_MODE 表示进程已按别的套间模型初始化过——接口照样能用，
        # 但这次初始化不属于我们，退出时绝不能替别人 CoUninitialize。
        if hr == RPC_E_CHANGED_MODE:
            debuglog.log("uia.client: COM already initialized in another mode")
        elif hr < 0:
            debuglog.log("uia.client: CoInitializeEx failed hr=0x%08x" % (hr & 0xFFFFFFFF))
            return None
        else:
            _COM_OWNED = True
        ole32.CoCreateInstance.restype = ctypes.c_long
        ole32.CoCreateInstance.argtypes = (
            ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
        instance = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(_CLSID_CUIAUTOMATION), None, 0x1,
            ctypes.byref(_IID_IUIAUTOMATION), ctypes.byref(instance))
        if hr < 0 or not instance:
            return None
        _UIA_CLIENT = instance
        return _UIA_CLIENT
    except Exception:
        debuglog.exception('uia.client')
        return None


def range_rect(text_range):
    """Return the first UIA text-range rectangle, expanding a collapsed caret."""
    vtable = com_vtable(text_range)
    expand = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.c_int)(vtable[6])
    expand(text_range, 0)   # TextUnit_Character; does not alter the real selection

    safe_array = ctypes.c_void_p()
    get_rects = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p))(vtable[10])
    if get_rects(text_range, ctypes.byref(safe_array)) < 0 or not safe_array:
        return None
    try:
        oleaut32 = ctypes.windll.oleaut32
        lower, upper = ctypes.c_long(), ctypes.c_long()
        if oleaut32.SafeArrayGetLBound(safe_array, 1, ctypes.byref(lower)) < 0:
            return None
        if oleaut32.SafeArrayGetUBound(safe_array, 1, ctypes.byref(upper)) < 0:
            return None
        count = upper.value - lower.value + 1
        if count < 4:
            return None
        data = ctypes.c_void_p()
        if oleaut32.SafeArrayAccessData(safe_array, ctypes.byref(data)) < 0:
            return None
        try:
            values = ctypes.cast(data, ctypes.POINTER(ctypes.c_double))
            x, y, width, height = (values[i] for i in range(4))
        finally:
            oleaut32.SafeArrayUnaccessData(safe_array)
        if width <= 0 or height <= 0:
            return None
        return QRect(round(x), round(y), max(1, round(width)), max(1, round(height)))
    finally:
        ctypes.windll.oleaut32.SafeArrayDestroy(safe_array)


def input_rects():
    """Use UI Automation TextPattern when the foreground app has no HWND caret."""
    uia_client = client()
    if not uia_client:
        return None, None
    element = pattern = ranges = text_range = None
    try:
        client_vtable = com_vtable(uia_client)
        element = ctypes.c_void_p()
        get_focused = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p))(client_vtable[8])
        if get_focused(uia_client, ctypes.byref(element)) < 0 or not element:
            return None, None

        element_vtable = com_vtable(element)
        pattern = ctypes.c_void_p()
        get_pattern = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_int,
            ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))(
                element_vtable[14])
        hr = get_pattern(element, UIA_TEXT_PATTERN_ID,
                         ctypes.byref(_IID_TEXT_PATTERN), ctypes.byref(pattern))
        if hr < 0 or not pattern:
            return None, None

        focus_rect = UIARECT()
        get_bounds = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p,
            ctypes.POINTER(UIARECT))(element_vtable[43])
        if get_bounds(element, ctypes.byref(focus_rect)) < 0:
            focus = None
        elif focus_rect.width > 0 and focus_rect.height > 0:
            focus = QRect(round(focus_rect.left), round(focus_rect.top),
                          round(focus_rect.width), round(focus_rect.height))
        else:
            focus = None

        pattern_vtable = com_vtable(pattern)
        ranges = ctypes.c_void_p()
        get_selection = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p))(pattern_vtable[5])
        if get_selection(pattern, ctypes.byref(ranges)) < 0 or not ranges:
            return None, focus

        ranges_vtable = com_vtable(ranges)
        length = ctypes.c_int()
        get_length = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int))(ranges_vtable[3])
        if get_length(ranges, ctypes.byref(length)) < 0 or length.value < 1:
            return None, focus
        text_range = ctypes.c_void_p()
        get_element = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p))(ranges_vtable[4])
        if get_element(ranges, 0, ctypes.byref(text_range)) < 0 or not text_range:
            return None, focus
        return range_rect(text_range), focus
    except Exception:
        debuglog.exception('uia.input_rects')
        return None, None
    finally:
        for pointer in (text_range, ranges, pattern, element):
            com_release(pointer)


def candidate_rect(caret):
    """Probe UI Automation under the caret for a rendered IME candidate bar.

    Newer WeType builds render the candidate UI in TextInputHost without a
    useful top-level HWND or IMM winapi.CANDIDATEFORM.  ElementFromPoint still
    exposes the individual candidate controls and their screen bounds.
    """
    uia_client = client()
    if not uia_client or caret is None or caret.isNull() or not caret.isValid():
        return None
    try:
        client_vtable = com_vtable(uia_client)
        element_from_point = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, wintypes.POINT,
            ctypes.POINTER(ctypes.c_void_p))(client_vtable[7])
        candidates = []
        x_values = (caret.left() + 2, caret.right() + 12,
                    caret.right() + 48, caret.right() + 96,
                    caret.right() + 180, caret.right() + 300)
        y_values = (caret.bottom() + 4, caret.bottom() + 12,
                    caret.bottom() + 24, caret.bottom() + 40,
                    caret.bottom() + 60, caret.top() - 4)
        for x in x_values:
            for y in y_values:
                element = ctypes.c_void_p()
                try:
                    point = wintypes.POINT(int(x), int(y))
                    if (element_from_point(uia_client, point,
                                           ctypes.byref(element)) < 0
                            or not element):
                        continue
                    bounds = UIARECT()
                    get_bounds = ctypes.WINFUNCTYPE(
                        ctypes.c_long, ctypes.c_void_p,
                        ctypes.POINTER(UIARECT))(com_vtable(element)[43])
                    if get_bounds(element, ctypes.byref(bounds)) < 0:
                        continue
                    rect = QRect(round(bounds.left), round(bounds.top),
                                 round(bounds.width), round(bounds.height))
                    score = placement.candidate_score(rect, caret)
                    if score is not None:
                        candidates.append((score, rect))
                finally:
                    com_release(element)
        return min(candidates, key=lambda item: item[0])[1] if candidates else None
    except Exception:
        debuglog.exception('uia.candidate_rect')
        return None


def shutdown():
    """释放 UIA 客户端并配对 CoUninitialize；退出时由 app.main 调用。

    只有本模块自己成功初始化过 COM 才反初始化：进程若已被 Qt 或宿主按别的
    套间模型初始化，替对方 CoUninitialize 会把它的 COM 环境一起拆掉。"""
    global _UIA_CLIENT, _COM_OWNED
    if _UIA_CLIENT:
        try:
            com_release(_UIA_CLIENT)
        except Exception:
            debuglog.exception("uia.shutdown release")
        _UIA_CLIENT = None
    if _COM_OWNED:
        try:
            ctypes.windll.ole32.CoUninitialize()
        except Exception:
            debuglog.exception("uia.shutdown CoUninitialize")
        _COM_OWNED = False
