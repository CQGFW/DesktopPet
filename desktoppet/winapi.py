# -*- coding: utf-8 -*-
"""Win32 声明层：ctypes 结构体 / 常量、窗口与进程查询、系统"减少动态效果"开关。

只做对系统 API 的最薄封装，不含宠物业务逻辑。"""
import ctypes
import ctypes.wintypes as wintypes
import os
import sys
import time

from PySide6.QtCore import QRect

from . import debuglog

SPI_GETCLIENTAREAANIMATION = 0x1042
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_CAPTION = 0x00C00000
WS_POPUP = 0x80000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
WS_EX_LAYERED = 0x00080000

_INPUT_APIS_READY = False
_OWN_PROCESS_ID = None
# PID -> (exe 名, 失效时刻)；见 process_name() 对 PID 复用的说明
PROCESS_NAME_TTL = 30.0
PROCESS_NAME_CACHE_MAX = 512
_WINDOW_PROCESS_NAMES = {}


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND),
                ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND),
                ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND),
                ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


class CANDIDATEFORM(ctypes.Structure):
    _fields_ = [("dwIndex", wintypes.DWORD),
                ("dwStyle", wintypes.DWORD),
                ("ptCurrentPos", wintypes.POINT),
                ("rcArea", wintypes.RECT)]

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def query_reduced_motion():
    """读取系统"减少动态效果"（Windows 的客户区动画开关）；查询失败按未开启处理。"""
    if sys.platform != "win32":
        return False
    try:
        enabled = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0)
        return bool(ok) and not enabled.value
    except Exception:
        debuglog.exception('query_reduced_motion')
        return False


def configure():
    """Declare pointer-sized Win32 signatures once before polling them."""
    global _INPUT_APIS_READY
    if _INPUT_APIS_READY:
        return True
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        user32.EnumWindows.restype = wintypes.BOOL
        user32.EnumWindows.argtypes = (WNDENUMPROC, wintypes.LPARAM)
        user32.EnumChildWindows.restype = wintypes.BOOL
        user32.EnumChildWindows.argtypes = (wintypes.HWND, WNDENUMPROC, wintypes.LPARAM)
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = (wintypes.HWND,)
        user32.GetGUIThreadInfo.restype = wintypes.BOOL
        user32.GetGUIThreadInfo.argtypes = (
            wintypes.DWORD, ctypes.POINTER(GUITHREADINFO))
        user32.ClientToScreen.restype = wintypes.BOOL
        user32.ClientToScreen.argtypes = (
            wintypes.HWND, ctypes.POINTER(wintypes.POINT))
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = (
            wintypes.HWND, ctypes.POINTER(wintypes.RECT))

        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcessId.restype = wintypes.DWORD
        kernel32.GetCurrentProcessId.argtypes = ()
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (
            wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.QueryFullProcessImageNameW.argtypes = (
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

        imm32 = ctypes.windll.imm32
        imm32.ImmGetContext.restype = wintypes.HANDLE
        imm32.ImmGetContext.argtypes = (wintypes.HWND,)
        imm32.ImmGetCandidateWindow.restype = wintypes.BOOL
        imm32.ImmGetCandidateWindow.argtypes = (
            wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(CANDIDATEFORM))
        imm32.ImmReleaseContext.restype = wintypes.BOOL
        imm32.ImmReleaseContext.argtypes = (wintypes.HWND, wintypes.HANDLE)
        _INPUT_APIS_READY = True
        return True
    except Exception:
        debuglog.exception('configure')
        return False


def window_rect(hwnd):
    """Return a valid top-level/client window rectangle in screen coordinates."""
    if not hwnd or not configure():
        return None
    try:
        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        return QRect(rect.left, rect.top,
                     rect.right - rect.left, rect.bottom - rect.top)
    except Exception:
        debuglog.exception('window_rect')
        return None


def client_rect_to_screen(hwnd, rect):
    """Convert a Win32 client-coordinate RECT to a non-empty Qt screen QRect."""
    if not configure():
        return None
    try:
        user32 = ctypes.windll.user32
        top_left = wintypes.POINT(rect.left, rect.top)
        bottom_right = wintypes.POINT(rect.right, rect.bottom)
        if not user32.ClientToScreen(hwnd, ctypes.byref(top_left)):
            return None
        if not user32.ClientToScreen(hwnd, ctypes.byref(bottom_right)):
            return None
        width = max(1, bottom_right.x - top_left.x)
        height = max(1, bottom_right.y - top_left.y)
        return QRect(top_left.x, top_left.y, width, height)
    except Exception:
        debuglog.exception('client_rect_to_screen')
        return None


def is_generic_popup_style(style, exstyle):
    """Accept only borderless, non-activating top-level popup candidates."""
    return (bool(style & WS_POPUP)
            and not bool(style & (WS_CHILD | WS_CAPTION))
            and bool(exstyle & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
                                | WS_EX_TOPMOST | WS_EX_LAYERED)))


def own_process_id():
    """本进程 PID：用于把宠物自己的窗口排除在候选框识别之外。

    气泡是无边框 / 置顶 / 分层的 Tool 窗口，尺寸也落在候选条的判定区间内，
    按窗口样式识别时会被当成 IME 候选框，导致宠物躲避自己弹出的气泡。
    按 PID 排除比比对 exe 名可靠，也不受源码运行 / 改名打包的影响。"""
    global _OWN_PROCESS_ID
    if _OWN_PROCESS_ID is None:
        _OWN_PROCESS_ID = int(ctypes.windll.kernel32.GetCurrentProcessId())
    return _OWN_PROCESS_ID


def window_process_id(hwnd):
    process_id = wintypes.DWORD()
    if not ctypes.windll.user32.GetWindowThreadProcessId(
            hwnd, ctypes.byref(process_id)):
        return None
    return process_id.value


def process_name(process_id):
    """PID → 小写 exe 名。带 TTL 与容量上限的缓存。

    Windows 会复用 PID：进程退出后同一个 PID 可能被新进程占用，永久缓存会把
    新进程认成旧进程（例如误判为输入法）。查询本身要 OpenProcess，逐窗口做
    创建时间校验代价太高，因此改用短 TTL——过期条目重新解析，误判最多只在
    一个 TTL 窗口内存在。上限则防止长时间运行后字典无界增长。"""
    now = time.monotonic()
    cached = _WINDOW_PROCESS_NAMES.get(process_id)
    if cached is not None and now < cached[1]:
        return cached[0]

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)):
            return None
        name = os.path.basename(buffer.value).lower()
        if len(_WINDOW_PROCESS_NAMES) >= PROCESS_NAME_CACHE_MAX:
            _prune_process_names(now)
        _WINDOW_PROCESS_NAMES[process_id] = (name, now + PROCESS_NAME_TTL)
        return name
    finally:
        kernel32.CloseHandle(handle)


def _prune_process_names(now):
    """先清过期条目；仍然超限就整表丢弃（重建成本只是几次 OpenProcess）。"""
    for pid in [pid for pid, (_, deadline) in _WINDOW_PROCESS_NAMES.items()
                if now >= deadline]:
        del _WINDOW_PROCESS_NAMES[pid]
    if len(_WINDOW_PROCESS_NAMES) >= PROCESS_NAME_CACHE_MAX:
        _WINDOW_PROCESS_NAMES.clear()
