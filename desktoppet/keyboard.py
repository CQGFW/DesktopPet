# -*- coding: utf-8 -*-
"""全局键盘监听：后台线程挂 WH_KEYBOARD_LL 低阶钩子并泵消息。"""
import ctypes
import ctypes.wintypes as wintypes
import sys
import threading

from PySide6.QtCore import QObject, Signal

from . import debuglog

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
WM_KEYUP, WM_SYSKEYUP = 0x0101, 0x0105
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000
LLKHF_EXTENDED = 0x01           # 扩展键位（如小键盘 Enter），参与物理键标识
LLKHF_INJECTED = 0x10           # 软件合成按键（SendInput 等），不触发拍击
KB_TAP_HOLD_MS = 90         # 脚掌压在键上的保持时长
KB_TAP_LIFT_MS = 130        # 抬回悬停位的过渡时长


# 左手区按键：ESC/Tab/Caps/左Shift/左Ctrl/Win/Alt、1~6、QWERT、ASDFG、ZXCVB
LEFT_VKS = frozenset(
    [0x1B, 0x09, 0x14, 0xA0, 0xA2, 0x5B, 0xA4]
    + list(range(0x31, 0x37))
    + [ord(c) for c in "QWERTASDFGZXCVB"])
RIGHT_VKS = frozenset(
    [0x08, 0x0D, 0xA1, 0xA3, 0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xDB, 0xDC, 0xDD, 0xDE]
    + [0x30, 0x37, 0x38, 0x39]
    + [ord(c) for c in "YUIOPHJKLNM"])


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", wintypes.WPARAM)]   # ULONG_PTR


class KeyListener(QObject):
    """全局键盘监听：后台线程挂 WH_KEYBOARD_LL 低阶钩子 + 消息循环。
    物理按键按下 / 松开时发 pressed(vk, key_id) / released(vk, key_id) 信号
    （跨线程队列投递到主线程）；key_id 由 scanCode + 扩展位组成，用于区分
    共享同一 vkCode 的物理键（如主键盘 / 小键盘 Enter）。注入的合成按键忽略。
    仅监听不拦截（总是 CallNextHookEx 放行）。钩子安装失败发 failed 信号。
    先连好信号再调 start()；stop() 阻塞等待线程解钩退出。"""
    pressed = Signal(int, int)
    released = Signal(int, int)
    failed = Signal()

    def __init__(self):
        super().__init__()
        self._tid = None
        self._started = threading.Event()   # 消息队列就绪或安装失败后置位
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def _fail(self, reason):
        """报告"钩子不可用"。

        必须在钩子线程内调用：跨线程 emit 会排队到主线程事件循环，等 Pet 构造
        完成后才投递。若改成在 start() 里同步 emit，槽会在 Pet.__init__ 中途运行，
        碰到尚未初始化的属性。"""
        debuglog.log("KeyListener unavailable: %s" % reason)
        self._started.set()       # 失败也置位，stop() 不必等超时
        try:
            self.failed.emit()
        except RuntimeError:
            pass                  # 退出阶段 QObject 已销毁

    def _run(self):
        if sys.platform != "win32":
            self._fail("global keyboard hook requires Windows")
            return
        try:
            self._hook_and_pump()
        except Exception:
            debuglog.exception("KeyListener thread")
            self._fail("hook thread crashed")

    def _hook_and_pump(self):
        user32 = ctypes.windll.user32
        HOOKPROC = ctypes.WINFUNCTYPE(
            wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = (
            ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
        user32.CallNextHookEx.restype = wintypes.LPARAM
        user32.CallNextHookEx.argtypes = (
            ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.UnhookWindowsHookEx.argtypes = (ctypes.c_void_p,)
        user32.GetMessageW.restype = ctypes.c_int
        user32.GetMessageW.argtypes = (
            ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
        user32.PeekMessageW.restype = wintypes.BOOL
        user32.PeekMessageW.argtypes = (
            ctypes.POINTER(wintypes.MSG), wintypes.HWND,
            wintypes.UINT, wintypes.UINT, wintypes.UINT)

        def proc(n_code, w_param, l_param):
            if n_code >= 0:
                kb = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT))[0]
                if not (kb.flags & LLKHF_INJECTED):
                    key_id = int(kb.scanCode) | ((int(kb.flags) & LLKHF_EXTENDED) << 16)
                    try:
                        if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                            self.pressed.emit(int(kb.vkCode), key_id)
                        elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                            self.released.emit(int(kb.vkCode), key_id)
                    except RuntimeError:
                        pass   # 退出阶段 QObject 已销毁
            return user32.CallNextHookEx(None, n_code, w_param, l_param)

        self._proc = HOOKPROC(proc)   # 持有引用，防止回调被 GC
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        if not hook:
            self._fail("SetWindowsHookExW returned NULL")
            return
        try:
            msg = wintypes.MSG()
            # PeekMessage 强制创建本线程消息队列，之后 stop() 的投递才可达
            user32.PeekMessageW(ctypes.byref(msg), None, WM_QUIT, WM_QUIT, PM_NOREMOVE)
            self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
            self._started.set()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                pass
        finally:
            user32.UnhookWindowsHookEx(ctypes.c_void_p(hook))

    def stop(self):
        """通知钩子线程退出并等待其解钩结束（最多 1 秒）。"""
        if not self._thread.is_alive():
            return
        if self._started.wait(timeout=1.0) and self._tid:
            if not ctypes.windll.user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0):
                return    # 投递失败：不再空等，线程为 daemon 随进程退出
        self._thread.join(timeout=1.0)
