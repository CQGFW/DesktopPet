# -*- coding: utf-8 -*-
"""桌面宠物 V2 分支（PySide6）：基于 V1（pet.py）的交互动画调整版。

与 V1 的差异：
- 移除待机随机走动（左右平移）与走路起伏；
- 新增呼吸动画：脚底锚定的轻微纵向起伏（横向反相、近似保体积），
  亚像素浮点绘制，循环平滑、无位置漂移；
- 新增头部跟随：鼠标悬停在猫咪身上时，头部绕颈部转轴朝鼠标方向平滑转动
  （限制最大角度），鼠标移出后平滑回正；
- 系统开启"减少动态效果"时，自动关闭呼吸 / 头部跟随 / 点击动画（气泡保留）；
- 新增闲置提醒：一段时间未与宠物互动（点击 / 拖拽 / 悬停 / 滚轮 / 右键）时，
  自动从语录里随机弹一条气泡，互动后重新计时；
- 右键菜单新增"始终置顶"开关（默认开启）；
- 右键菜单新增"自动走动"开关（默认关闭）：开启后宠物在当前屏幕右下 1/4
  区域内随机游走（匀速走向随机目标点，到达后停留数秒再选下一个），
  拖拽 / 菜单打开 / 减少动态效果时暂停。
- 新增键盘互动（BongoCat 风格，默认开启，可右键关闭）：身前放一块小键盘，
  全局低阶键盘钩子检测敲键，按键在 QWERTY 左半区用左脚、右半区用右脚、
  其余键交替，脚掌拍下后平滑抬回；减少动态效果时不响应。
- 新增输入光标跟随：前台文本控件输入时移动到插入光标附近，临时缩小为
  输入前比例的 20%，避开输入控件和 IME 候选区域；停止输入后恢复。

其余与 V1 相同：点击弹语录气泡并轮流触发互动动画（跳跃 → 压扁回弹 → 左右
抖动）、拖拽、滚轮缩放（25%~150%，脚底不动）、右键菜单退出。"""
import ctypes
import ctypes.wintypes as wintypes
import math
import os
import sys
import random
import threading
import time
import uuid
from collections import namedtuple

from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QRectF, QObject, Signal
from PySide6.QtGui import (QPixmap, QPainter, QColor, QFont, QFontMetrics,
                           QPainterPath, QImage, QLinearGradient)
from PySide6.QtWidgets import QApplication, QWidget, QMenu

BASE_H = 260          # 100% 缩放时的显示高度
MIN_SCALE, MAX_SCALE = 0.25, 1.50
ZOOM_STEP = 1.08      # 每格滚轮的平滑步进

# 输入光标跟随：输入时临时缩小并避开输入控件 / IME 候选区域
INPUT_IDLE_MS = 1000
INPUT_POLL_MS = 50
INPUT_SCALE_FACTOR = 0.2
INPUT_GAP = 12
INPUT_COMPACT_FOCUS_MAX_H = 96
INPUT_IME_FALLBACK_W = 420
INPUT_IME_FALLBACK_H = 120

# 互动动画：点击时按此顺序轮流触发
ANIM_KINDS = ("jump", "squash", "shake")
ANIM_DUR = {"jump": 620, "squash": 520, "shake": 700}   # 毫秒
ANIM_TICK_MS = 15

FRAME_MS = 33         # 呼吸 / 头部跟随的动画帧间隔（约 30fps）

# 呼吸：纵向 ±1.5%、横向反相 ±0.6%（近似保体积），周期 3.4s，脚底锚定
BREATH_PERIOD = 3.4
BREATH_AMP_Y = 0.015
BREATH_AMP_X = 0.006

# 头部跟随（比例均相对整张猫图的宽 / 高）
HEAD_MAX_DEG = 12.0             # 最大转角，避免过度旋转脱离身体
HEAD_GAIN = 0.5                 # 鼠标方位角 → 头部目标角的映射比例
HEAD_TAU = 0.12                 # 角度平滑时间常数（秒）
HEAD_PIVOT = (0.66, 0.34)       # 颈部转轴位置
HEAD_CORE_X, HEAD_CORE_Y = 0.44, 0.30   # 头部核心区边界（身体图在此区内抠空）
HEAD_BAND_X, HEAD_BAND_Y = 0.08, 0.08   # 左 / 下羽化过渡带宽度（原位皮毛垫底遮缝）
ERASE_MX, ERASE_MY = 0.07, 0.06         # 抠空区边缘的渐变余量：转头后由静态皮毛补位

SPI_GETCLIENTAREAANIMATION = 0x1042

# 键盘互动（BongoCat 风格）：全局低阶键盘钩子检测敲键，宠物用两只脚拍打
# 身前的小键盘；按键位于 QWERTY 左半区用左脚、右半区用右脚，其余键交替。
WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
WM_KEYUP, WM_SYSKEYUP = 0x0101, 0x0105
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000
LLKHF_EXTENDED = 0x01           # 扩展键位（如小键盘 Enter），参与物理键标识
LLKHF_INJECTED = 0x10           # 软件合成按键（SendInput 等），不触发拍击
KB_TAP_HOLD_MS = 90         # 脚掌压在键上的保持时长
KB_TAP_LIFT_MS = 130        # 抬回悬停位的过渡时长
# 脚掌图层（比例相对整张猫图）：从原图裁出两只前脚（边缘羽化），
# 静止时原位叠回与原图逐像素重合；敲键时顶端固定、向下拉伸压到键盘上
# （拉伸而非平移：身体不必抠空，也不会露出空缺）
PAW_TOP = 0.74                          # 脚部图层上边界（含小腿，摊薄拉伸比例）
PAW_SPANS = ((0.50, 0.69), (0.69, 0.86))    # 左 / 右脚的水平范围
PAW_FEATHER_Y = 0.10                    # 上边羽化带（拉伸后与身体无缝衔接）
PAW_FEATHER_X = 0.018                   # 左右羽化带
PAW_PRESS_FRAC = 0.45                   # 下压幅度（相对键盘高度）
# 左手区按键：ESC/Tab/Caps/左Shift/左Ctrl/Win/Alt、1~6、QWERT、ASDFG、ZXCVB
LEFT_VKS = frozenset(
    [0x1B, 0x09, 0x14, 0xA0, 0xA2, 0x5B, 0xA4]
    + list(range(0x31, 0x37))
    + [ord(c) for c in "QWERTASDFGZXCVB"])
RIGHT_VKS = frozenset(
    [0x08, 0x0D, 0xA1, 0xA3, 0xBA, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xDB, 0xDC, 0xDD, 0xDE]
    + [0x30, 0x37, 0x38, 0x39]
    + [ord(c) for c in "YUIOPHJKLNM"])

# 闲置提醒：距上次互动超过随机间隔时自动弹一条语录；间隔每次在区间内随机取值
IDLE_MIN_MS = 90_000
IDLE_MAX_MS = 180_000

# 自动走动：限定在当前屏幕可用区域的右下 1/4；匀速走向随机目标，到达后停留
WALK_TICK_MS = 33
WALK_SPEED = 60                 # 像素/秒
WALK_PAUSE_MIN_MS = 2_000       # 到达目标后停留时长的随机区间
WALK_PAUSE_MAX_MS = 6_000

InputContext = namedtuple("InputContext", "caret focus candidate screen")

QUOTES = [
    "喵~ 今天也要加油鸭！",
    "本喵盯着你工作呢，别摸鱼！",
    "铲屎官，罐罐时间到了吗？",
    "刚睡醒，梦见一条大鱼……",
    "摸我可以，但要付猫粮。",
    "你的代码有 bug 的味道。",
    "晒太阳的日子最舒服啦~",
    "陪本喵玩一会儿嘛！",
    "喵生苦短，及时打盹。",
    "今天的你也很好看哦~",
    "工作再忙，也要记得喝水！",
    "本喵才是这台电脑的主人。",
]


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


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
        return False


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


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WECHAT_IME_PROCESSES = {"wetype_renderer.exe"}
_WINDOW_PROCESS_NAMES = {}


_INPUT_APIS_READY = False
_UIA_CLIENT = None
_CLSID_CUIAUTOMATION = GUID.parse("ff48dba4-60ef-4201-aa87-54103eef594e")
_IID_IUIAUTOMATION = GUID.parse("30cbe57d-d9d0-452a-ab13-7ac5ac4825ee")
_IID_TEXT_PATTERN = GUID.parse("32e215ea-9c15-4268-8173-ee0c0eaf366c")
UIA_TEXT_PATTERN_ID = 10014


def _configure_input_apis():
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
        return False


def _com_vtable(pointer):
    return ctypes.cast(
        pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents


def _com_release(pointer):
    if pointer:
        release = ctypes.WINFUNCTYPE(
            wintypes.ULONG, ctypes.c_void_p)(_com_vtable(pointer)[2])
        release(pointer)


def _uia_client():
    """Create the process-local UI Automation client lazily on the GUI thread."""
    global _UIA_CLIENT
    if _UIA_CLIENT:
        return _UIA_CLIENT
    if sys.platform != "win32":
        return None
    try:
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(None, 0x2)   # already initialized is also usable
        ole32.CoCreateInstance.restype = ctypes.c_long
        ole32.CoCreateInstance.argtypes = (
            ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
        client = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(_CLSID_CUIAUTOMATION), None, 0x1,
            ctypes.byref(_IID_IUIAUTOMATION), ctypes.byref(client))
        if hr < 0 or not client:
            return None
        _UIA_CLIENT = client
        return _UIA_CLIENT
    except Exception:
        return None


def _uia_range_rect(text_range):
    """Return the first UIA text-range rectangle, expanding a collapsed caret."""
    vtable = _com_vtable(text_range)
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


def _uia_input_rects():
    """Use UI Automation TextPattern when the foreground app has no HWND caret."""
    client = _uia_client()
    if not client:
        return None, None
    element = pattern = ranges = text_range = None
    try:
        client_vtable = _com_vtable(client)
        element = ctypes.c_void_p()
        get_focused = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p))(client_vtable[8])
        if get_focused(client, ctypes.byref(element)) < 0 or not element:
            return None, None

        element_vtable = _com_vtable(element)
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

        pattern_vtable = _com_vtable(pattern)
        ranges = ctypes.c_void_p()
        get_selection = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p))(pattern_vtable[5])
        if get_selection(pattern, ctypes.byref(ranges)) < 0 or not ranges:
            return None, focus

        ranges_vtable = _com_vtable(ranges)
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
        return _uia_range_rect(text_range), focus
    except Exception:
        return None, None
    finally:
        for pointer in (text_range, ranges, pattern, element):
            _com_release(pointer)


def _window_rect(hwnd):
    """Return a valid top-level/client window rectangle in screen coordinates."""
    if not hwnd or not _configure_input_apis():
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
        return None


def _client_rect_to_screen(hwnd, rect):
    """Convert a Win32 client-coordinate RECT to a non-empty Qt screen QRect."""
    if not _configure_input_apis():
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
        return None


def _candidate_form_rect(form):
    """Convert a CANDIDATEFORM to its screen-space exclusion rectangle."""
    if (form.rcArea.right > form.rcArea.left
            and form.rcArea.bottom > form.rcArea.top):
        return QRect(form.rcArea.left, form.rcArea.top,
                     form.rcArea.right - form.rcArea.left,
                     form.rcArea.bottom - form.rcArea.top)
    return QRect(form.ptCurrentPos.x, form.ptCurrentPos.y,
                 INPUT_IME_FALLBACK_W, INPUT_IME_FALLBACK_H)


def _ime_candidate_rect(hwnd):
    """Read the traditional IMM candidate exclusion area, when one is exposed.

    CANDIDATEFORM coordinates are already in screen coordinates.  They must
    not be passed through ClientToScreen, unlike GUITHREADINFO.rcCaret above.
    """
    if not hwnd or not _configure_input_apis():
        return None
    try:
        imm32 = ctypes.windll.imm32
        himc = imm32.ImmGetContext(hwnd)
        if not himc:
            return None
        try:
            form = CANDIDATEFORM()
            form.dwIndex = 0
            if not imm32.ImmGetCandidateWindow(himc, 0, ctypes.byref(form)):
                return None
            return _candidate_form_rect(form)
        finally:
            imm32.ImmReleaseContext(hwnd, himc)
    except Exception:
        return None


def _select_wechat_candidate(caret, windows):
    nearby = []
    for process_name, rect in windows:
        if process_name.lower() not in WECHAT_IME_PROCESSES:
            continue
        if not (80 <= rect.width() <= 1200 and 24 <= rect.height() <= 180):
            continue
        dx = max(rect.left() - caret.right(), caret.left() - rect.right(), 0)
        dy = max(rect.top() - caret.bottom(), caret.top() - rect.bottom(), 0)
        if dx <= 240 and dy <= 240:
            nearby.append((dx * dx + dy * dy, -rect.width(), rect))
    return min(nearby, key=lambda item: (item[0], item[1]))[2] if nearby else None


def _window_process_name(hwnd):
    process_id = wintypes.DWORD()
    if not ctypes.windll.user32.GetWindowThreadProcessId(
            hwnd, ctypes.byref(process_id)):
        return None
    if process_id.value in _WINDOW_PROCESS_NAMES:
        return _WINDOW_PROCESS_NAMES[process_id.value]

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, process_id.value)
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)):
            return None
        name = os.path.basename(buffer.value).lower()
        _WINDOW_PROCESS_NAMES[process_id.value] = name
        return name
    finally:
        kernel32.CloseHandle(handle)


def _wechat_candidate_rect(caret):
    if not _configure_input_apis():
        return None
    windows = []
    user32 = ctypes.windll.user32

    @WNDENUMPROC
    def collect(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            process_name = _window_process_name(hwnd)
            if process_name in WECHAT_IME_PROCESSES:
                rect = _window_rect(hwnd)
                if rect is not None:
                    windows.append((process_name, rect))
        return True

    try:
        if not user32.EnumWindows(collect, 0):
            return None
        return _select_wechat_candidate(caret, windows)
    except Exception:
        return None


def query_input_context():
    """Return the foreground caret and exclusion rectangles, or None on failure."""
    if not _configure_input_apis():
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

        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        has_gui_info = bool(user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)))
        if has_gui_info and info.hwndCaret:
            caret = _client_rect_to_screen(info.hwndCaret, info.rcCaret)
            focus = _window_rect(info.hwndFocus or info.hwndCaret)
        else:
            caret, focus = _uia_input_rects()
        if caret is None:
            return None
        ime_hwnd = (info.hwndFocus or info.hwndCaret) if has_gui_info else foreground
        wechat_candidate = _wechat_candidate_rect(caret)
        candidate = (wechat_candidate if wechat_candidate is not None
                     else _ime_candidate_rect(ime_hwnd))
        screen_obj = QApplication.screenAt(caret.center()) or QApplication.primaryScreen()
        if screen_obj is None:
            return None
        return InputContext(caret, focus, candidate, screen_obj.availableGeometry())
    except Exception:
        return None


def _input_safe_position(caret, focus, candidate, pet_size, screen, gap=INPUT_GAP):
    """Choose a screen-contained pet position, preferring below the caret."""
    width, height = pet_size.width(), pet_size.height()
    max_x = screen.right() - width + 1
    max_y = screen.bottom() - height + 1

    def clamp_x(x):
        return max(screen.left(), min(x, max_x))

    def clamp_y(y):
        return max(screen.top(), min(y, max_y))

    avoids = []
    if focus is not None and not focus.isNull() and focus.isValid():
        compact_limit = max(INPUT_COMPACT_FOCUS_MAX_H,
                            pet_size.height() + gap * 2,
                            caret.height() * 4)
        # 文档编辑器常把整页作为焦点控件；避开整页会把宠物推到屏幕底部。
        # 紧凑输入框避开完整边界，多行编辑区只避开光标本身与 IME 区域。
        if focus.contains(caret.center()) and focus.height() <= compact_limit:
            avoids.append(focus.adjusted(-gap, -gap, gap, gap))
    if candidate is not None and not candidate.isNull() and candidate.isValid():
        avoids.append(candidate.adjusted(-gap, -gap, gap, gap))

    center_x = clamp_x(caret.center().x() - width // 2)
    below_y = caret.bottom() + gap + 1
    for _ in range(len(avoids) + 1):
        probe = QRect(center_x, below_y, width, height)
        hits = [rect for rect in avoids if probe.intersects(rect)]
        if not hits:
            break
        below_y = max(rect.bottom() + 1 for rect in hits)

    candidates = [(center_x, below_y),
                  (center_x, caret.top() - gap - height),
                  (caret.left() - gap - width,
                   caret.center().y() - height // 2),
                  (caret.right() + gap + 1,
                   caret.center().y() - height // 2)]

    for x, y in candidates:
        rect = QRect(clamp_x(x), y, width, height)
        if screen.contains(rect) and not any(rect.intersects(a) for a in avoids):
            return rect.topLeft()

    return QPoint(clamp_x(center_x), clamp_y(below_y))


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

    def _run(self):
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
            self._started.set()       # 失败也置位，stop() 不必等超时
            try:
                self.failed.emit()
            except RuntimeError:
                pass
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


class Bubble(QWidget):
    """对话气泡：圆角白底 + 小尾巴，逐像素透明，2 秒自动消失。"""
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool
                         | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.text = ""
        self.tail_down = True   # 尾巴朝下（气泡在猫上方）
        self.tail_x = 0.5       # 尾巴水平位置（0~1）
        self.font = QFont("Microsoft YaHei", 11)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    PAD_X, PAD_Y, TAIL = 14, 9, 10

    def popup(self, text, anchor_x, anchor_y, above, screen):
        """anchor 为尾巴尖端应指向的点；above=True 表示气泡显示在锚点上方。"""
        self.text = text
        fm = QFontMetrics(self.font)
        tw = min(fm.horizontalAdvance(text), 260)
        rect = fm.boundingRect(0, 0, tw, 1000, Qt.TextWordWrap, text)
        w = rect.width() + self.PAD_X * 2
        h = rect.height() + self.PAD_Y * 2 + self.TAIL
        self.tail_down = above
        x = anchor_x - w // 2
        x = max(screen.left() + 4, min(x, screen.right() - w - 4))
        self.tail_x = min(0.9, max(0.1, (anchor_x - x) / w))
        y = anchor_y - h if above else anchor_y
        self.setGeometry(x, y, w, h)
        self.show()
        self.update()
        self.timer.start(2000)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h, t = self.width(), self.height(), self.TAIL
        body = QRectF(0, 0 if self.tail_down else t, w, h - t)
        path = QPainterPath()
        path.addRoundedRect(body, 12, 12)
        # 小尾巴三角
        tx = self.tail_x * w
        if self.tail_down:
            path.moveTo(tx - 8, body.bottom()); path.lineTo(tx, h); path.lineTo(tx + 8, body.bottom())
        else:
            path.moveTo(tx - 8, body.top()); path.lineTo(tx, 0); path.lineTo(tx + 8, body.top())
        path.closeSubpath()
        p.setPen(QColor(180, 150, 120))
        p.setBrush(QColor(255, 252, 245, 242))
        p.drawPath(path)
        p.setPen(QColor(80, 60, 45))
        p.setFont(self.font)
        p.drawText(body.adjusted(self.PAD_X, self.PAD_Y, -self.PAD_X, -self.PAD_Y),
                   Qt.AlignCenter | Qt.TextWordWrap, self.text)


class Pet(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)   # 重新显示时不抢占焦点
        self.setMouseTracking(True)   # 无按键悬停也接收 mouseMove，用于头部跟随

        self.src = QPixmap(resource_path("cat_soft.png"))   # 高清羽化素材
        self.scale = 1.0
        self.kb_enabled = True    # 键盘互动开关（影响底部键盘区留白）
        self.dragging = False
        self.drag_offset = QPoint()
        self._press_pos = None

        # 互动动画状态
        self.anim_kind = None
        self.anim_t = 0.0
        self.anim_index = 0
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(ANIM_TICK_MS)
        self.anim_timer.timeout.connect(self._anim_tick)

        # 呼吸 / 头部跟随状态
        self.reduced_motion = query_reduced_motion()
        self.t0 = time.monotonic()
        self.head_angle = 0.0     # 当前头部角度（度，正值向右倾）
        self.head_target = 0.0
        self.hover_pos = None     # 悬停时的窗口内坐标；None 表示不在窗口内

        self._build_layers()
        self._rebuild_pixmap()

        scr = QApplication.primaryScreen().availableGeometry()
        self.screen_rect = scr
        self._apply_geometry(scr.center().x(), scr.bottom() + 1)

        self.bubble = Bubble()
        self.last_quote = None    # 上一条语录，随机时避免连续重复

        self.menu = QMenu()
        self.act_topmost = self.menu.addAction("始终置顶")
        self.act_topmost.setCheckable(True)
        self.act_topmost.setChecked(True)
        self.act_topmost.toggled.connect(self._set_topmost)
        self.act_walk = self.menu.addAction("自动走动")
        self.act_walk.setCheckable(True)
        self.act_walk.setChecked(False)
        self.act_walk.toggled.connect(self._set_walk)
        self.act_kb = self.menu.addAction("键盘互动")
        self.act_kb.setCheckable(True)
        self.act_kb.setChecked(True)
        self.act_kb.toggled.connect(self._set_kb)
        self.menu.addSeparator()
        self.menu.addAction("退出", QApplication.quit)

        # 输入跟随：保存进入前的缩放 / 脚底位置，短周期刷新跨进程光标。
        self.input_follow_active = False
        self.input_saved_scale = None
        self.input_saved_foot = None
        self.input_idle_timer = QTimer(self)
        self.input_idle_timer.setSingleShot(True)
        self.input_idle_timer.timeout.connect(self._stop_input_follow)
        self.input_poll_timer = QTimer(self)
        self.input_poll_timer.setInterval(INPUT_POLL_MS)
        self.input_poll_timer.timeout.connect(self._input_follow_tick)

        # 键盘互动：全局钩子监听敲键，两只脚拍打身前小键盘。
        # _held 记录按住中的物理键标识 → 所用脚（忽略系统自动重复、松键配对）；
        # _paw_held[i] 为该脚当前按住的键数，>0 时脚保持压下；
        # _paw_lift[i] 为该脚开始抬起的时刻（保证快速敲击也有可见的按压段）
        self._held = {}
        self._paw_held = [0, 0]
        self._paw_lift = [-1e9, -1e9]
        self._paw_alt = 0            # 未知分区按键交替用脚
        self.key_listener = KeyListener()
        self.key_listener.pressed.connect(self._on_global_key)
        self.key_listener.released.connect(self._on_global_key_up)
        self.key_listener.failed.connect(self._on_kb_hook_failed)
        self.key_listener.start()    # 信号连好后再启动，避免漏掉 failed 通知

        # 自动走动状态：目标点为脚底中心的屏幕坐标，None 表示正在停留；
        # _walk_pos 为浮点脚底位置（避免逐帧取整累计出速度/方向量化误差）
        self.walk_enabled = False
        self.walk_target = None
        self._walk_pos = None
        self.walk_timer = QTimer(self)
        self.walk_timer.setInterval(WALK_TICK_MS)
        self.walk_timer.timeout.connect(self._walk_tick)
        self.walk_pause_timer = QTimer(self)
        self.walk_pause_timer.setSingleShot(True)
        self.walk_pause_timer.timeout.connect(self._on_walk_pause_done)

        # 闲置提醒：超时无互动自动弹语录；任何互动（含悬停）重置计时
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(self._idle_chatter)
        self._reset_idle_timer()

        # 动画帧驱动（呼吸 + 头部角度平滑）；减少动态效果时自动静默
        self.frame_timer = QTimer(self)
        self.frame_timer.timeout.connect(self._frame)
        self.frame_timer.start(FRAME_MS)

        # 定期复查系统"减少动态效果"开关，随系统设置即时降级 / 恢复
        self.rm_timer = QTimer(self)
        self.rm_timer.timeout.connect(self._poll_reduced_motion)
        self.rm_timer.start(4000)

    # ---------- 头 / 身分层 ----------
    def _build_layers(self):
        """按原图分辨率把猫图拆成 body（头部核心区抠空）与 head（左 / 下边羽化）。
        0° 时 head 叠回 body 逐像素还原原图；转头时过渡带的原位皮毛垫底遮住接缝。
        只在启动时做一次，缩放时直接对两层按高度重采样。"""
        src = self.src.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
        w, h = src.width(), src.height()
        core_x = round(w * HEAD_CORE_X)
        core_y = round(h * HEAD_CORE_Y)
        band_x = round(w * HEAD_BAND_X)
        band_y = round(h * HEAD_BAND_Y)

        body = QImage(src)
        # 抠空蒙版：核心区内部全抠、左 / 下边缘按渐变过渡到不抠。
        # 转头让头层移开时，边缘处保留的静态皮毛垫底补位，避免露出直线接缝。
        mw, mh = w - core_x, core_y
        mx = round(w * ERASE_MX)
        my = round(h * ERASE_MY)
        mask = QImage(mw, mh, QImage.Format_ARGB32_Premultiplied)
        mask.fill(0)
        p = QPainter(mask)
        gx = QLinearGradient(0, 0, mx, 0)
        gx.setColorAt(0.0, QColor(0, 0, 0, 0))
        gx.setColorAt(1.0, QColor(0, 0, 0, 255))
        p.fillRect(0, 0, mx, mh, gx)
        p.fillRect(mx, 0, mw - mx, mh, QColor(0, 0, 0, 255))
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        gy = QLinearGradient(0, mh - my, 0, mh)
        gy.setColorAt(0.0, QColor(0, 0, 0, 255))
        gy.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, mh - my, mw, my, gy)
        p.end()
        p = QPainter(body)
        p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
        p.drawImage(core_x, 0, mask)
        p.end()

        crop_x = core_x - band_x
        crop_h = core_y + band_y
        head = src.copy(crop_x, 0, w - crop_x, crop_h)
        p = QPainter(head)
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        gx = QLinearGradient(0, 0, band_x, 0)
        gx.setColorAt(0.0, QColor(0, 0, 0, 0))
        gx.setColorAt(1.0, QColor(0, 0, 0, 255))
        p.fillRect(0, 0, band_x, crop_h, gx)
        gy = QLinearGradient(0, core_y, 0, crop_h)
        gy.setColorAt(0.0, QColor(0, 0, 0, 255))
        gy.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, core_y, head.width(), crop_h - core_y, gy)
        p.end()

        # 脚掌图层：从原图裁出两只前脚并羽化边缘。静止时原位叠回与原图
        # 逐像素重合（身体不抠空）；敲键时向下拉伸覆盖，不会露出空缺
        self.paw_srcs = []
        self.paw_fracs = []     # (x, y, w, h) 在整图中的比例
        py0 = round(h * PAW_TOP)
        fy = round(h * PAW_FEATHER_Y)
        fx = round(w * PAW_FEATHER_X)
        for x0, x1 in PAW_SPANS:
            rx0, rx1 = round(w * x0), round(w * x1)
            pw, ph = rx1 - rx0, h - py0
            paw = src.copy(rx0, py0, pw, ph)
            pp = QPainter(paw)
            pp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            gy = QLinearGradient(0, 0, 0, fy)
            gy.setColorAt(0.0, QColor(0, 0, 0, 0))
            gy.setColorAt(1.0, QColor(0, 0, 0, 255))
            pp.fillRect(0, 0, pw, fy, gy)
            gxl = QLinearGradient(0, 0, fx, 0)
            gxl.setColorAt(0.0, QColor(0, 0, 0, 0))
            gxl.setColorAt(1.0, QColor(0, 0, 0, 255))
            pp.fillRect(0, 0, fx, ph, gxl)
            gxr = QLinearGradient(pw - fx, 0, pw, 0)
            gxr.setColorAt(0.0, QColor(0, 0, 0, 255))
            gxr.setColorAt(1.0, QColor(0, 0, 0, 0))
            pp.fillRect(pw - fx, 0, fx, ph, gxr)
            pp.end()
            self.paw_srcs.append(QPixmap.fromImage(paw))
            self.paw_fracs.append((rx0 / w, py0 / h, pw / w, ph / h))

        self.body_src = QPixmap.fromImage(body)
        self.head_src = QPixmap.fromImage(head)
        self.head_x_frac = crop_x / w    # head 层在整图中的水平起点比例
        self.head_h_frac = crop_h / h    # head 层高度占整图比例

    # ---------- 素材缩放与窗口几何 ----------
    def _rebuild_pixmap(self):
        hpx = round(BASE_H * self.scale)
        self.pix = self.src.scaledToHeight(hpx, Qt.SmoothTransformation)
        self.body_pix = self.body_src.scaledToHeight(hpx, Qt.SmoothTransformation)
        head_h = max(1, round(self.head_src.height() * hpx / self.src.height()))
        self.head_pix = self.head_src.scaledToHeight(head_h, Qt.SmoothTransformation)
        self.paw_pix = [
            ps.scaledToHeight(max(1, round(ps.height() * hpx / self.src.height())),
                              Qt.SmoothTransformation)
            for ps in self.paw_srcs]
        # 窗口内为动画预留的空间：头顶留跳跃高度，左右留抖动/压扁/转头的余量，
        # 底部留放小键盘的区域（键盘互动）
        self.top_pad = round(self.pix.height() * 0.32)
        self.side_pad = round(self.pix.width() * 0.15)
        self.bottom_pad = round(self.pix.height() * 0.12) if self.kb_enabled else 0

    def _apply_geometry(self, foot_x, foot_y):
        """按当前素材重设窗口尺寸，并保持脚底中心位于 (foot_x, foot_y)。"""
        w = self.pix.width() + 2 * self.side_pad
        h = self.pix.height() + self.top_pad + self.bottom_pad + 6
        self.resize(w, h)
        self.move(foot_x - w // 2, foot_y - h)

    def _set_scale(self, new_scale):
        foot_x = self.x() + self.width() // 2
        foot_y = self.y() + self.height()
        self.scale = new_scale
        self._rebuild_pixmap()
        self._apply_geometry(foot_x, foot_y)
        # 窗口尺寸变了：走动目标重新收进区域，浮点脚底下一帧从实际几何重建
        if self.walk_target is not None:
            fx, fy = self._clamp_foot(self.walk_target.x(), self.walk_target.y())
            self.walk_target = QPoint(fx, fy)
        self._walk_pos = None

    # ---------- 置顶开关 ----------
    def _set_topmost(self, on):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        # 气泡置顶状态随宠物同步，避免宠物被遮住时气泡还单独浮在最上层
        bubble_visible = self.bubble.isVisible()
        self.bubble.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        if bubble_visible:
            self.bubble.show()
        # 修改窗口标志会隐藏并重建原生窗口；延后到菜单的嵌套事件循环结束后
        # 再重新显示，配合 WA_ShowWithoutActivating 避免闪烁 / 抢占前台焦点
        QTimer.singleShot(0, self.show)

    # ---------- 自动走动 ----------
    def _walk_region(self):
        """走动限定区域：宠物当前所在屏幕可用区域的右下 1/4。"""
        scr = self._current_screen_rect()
        return QRect(scr.center(), scr.bottomRight())

    def _foot_bounds(self):
        """脚底中心点在走动区域内的合法区间 (lo_x, hi_x, lo_y, hi_y)：
        向内收缩半个窗口宽 / 整个窗口高，保证窗口整体不越出区域。"""
        r = self._walk_region()
        lo_x, hi_x = r.left() + self.width() // 2, r.right() - self.width() // 2
        lo_y, hi_y = r.top() + self.height(), r.bottom()
        if lo_x > hi_x:     # 区域比窗口还窄 / 矮时退化为贴中线 / 贴底
            lo_x = hi_x = r.center().x()   # （此时窗口不可避免会伸出区域）
        if lo_y > hi_y:
            lo_y = hi_y = r.bottom()
        return lo_x, hi_x, lo_y, hi_y

    def _clamp_foot(self, fx, fy):
        """把脚底中心点收进走动区域的合法区间。"""
        lo_x, hi_x, lo_y, hi_y = self._foot_bounds()
        return max(lo_x, min(fx, hi_x)), max(lo_y, min(fy, hi_y))

    def _walk_paused(self):
        """走动的临时暂停条件：拖拽 / 右键菜单打开 / 气泡显示中 / 减少动态效果。"""
        return (self.dragging or self.reduced_motion or self.input_follow_active
                or self.menu.isVisible() or self.bubble.isVisible())

    def _pick_walk_target(self):
        """在合法区间内均匀随机选下一个脚底目标点（不经 clamp，避免边缘聚集）。"""
        lo_x, hi_x, lo_y, hi_y = self._foot_bounds()
        self.walk_target = QPoint(random.randint(lo_x, hi_x),
                                  random.randint(lo_y, hi_y))
        self._walk_pos = None   # 下一 tick 从当前窗口位置重新起步

    def _on_walk_pause_done(self):
        """停留结束：若正处于暂停态则不选新目标（相当于冻结停留），
        恢复后由 _walk_tick 兜底重新计时。"""
        if self.walk_enabled and not self._walk_paused():
            self._pick_walk_target()

    def _set_walk(self, on):
        self.walk_enabled = on
        if on:
            self._pick_walk_target()
            self.walk_timer.start()
        else:
            self.walk_timer.stop()
            self.walk_pause_timer.stop()
            self.walk_target = None
            self._walk_pos = None

    def _restart_walk_pause(self):
        self.walk_pause_timer.start(
            random.randint(WALK_PAUSE_MIN_MS, WALK_PAUSE_MAX_MS))

    def _walk_tick(self):
        """每帧向目标匀速走一步；浮点累计位置，move 时才取整。"""
        if self._walk_paused():
            return
        if self.walk_target is None:
            # 停留计时被暂停冻结 / 外部打断后兜底重新排期
            if not self.walk_pause_timer.isActive():
                self._restart_walk_pause()
            return
        if self._walk_pos is None:
            self._walk_pos = (float(self.x() + self.width() // 2),
                              float(self.y() + self.height()))
        fx, fy = self._walk_pos
        dx = self.walk_target.x() - fx
        dy = self.walk_target.y() - fy
        dist = math.hypot(dx, dy)
        step = WALK_SPEED * WALK_TICK_MS / 1000.0
        if dist <= step:    # 到达：吸附到目标点并停留一会儿
            nx, ny = self.walk_target.x(), self.walk_target.y()
            self.walk_target = None
            self._walk_pos = None
            self._restart_walk_pause()
        else:
            fx += dx / dist * step
            fy += dy / dist * step
            self._walk_pos = (fx, fy)
            nx, ny = round(fx), round(fy)
        self.move(nx - self.width() // 2, ny - self.height())

    # ---------- 呼吸 / 头部跟随 ----------
    def _breath_scales(self, t):
        """呼吸缩放系数 (宽, 高)：纵向正弦起伏、横向轻微反相；减少动态效果时恒 1。"""
        if self.reduced_motion:
            return 1.0, 1.0
        ph = math.sin(2 * math.pi * (t - self.t0) / BREATH_PERIOD)
        return 1.0 - BREATH_AMP_X * ph, 1.0 + BREATH_AMP_Y * ph

    def _cat_rect(self):
        """当前猫咪主体（未叠加动画形变）的窗口内矩形。"""
        return QRect((self.width() - self.pix.width()) // 2,
                     self.height() - self.bottom_pad - self.pix.height() - 3,
                     self.pix.width(), self.pix.height())

    def _update_head_target(self):
        """按鼠标相对颈部转轴的方位更新头部目标角；不悬停 / 拖拽 / 降级时回正。"""
        if (self.reduced_motion or self.dragging or self.hover_pos is None
                or not self._cat_rect().contains(self.hover_pos)):
            self.head_target = 0.0
            return
        r = self._cat_rect()
        px = r.x() + r.width() * HEAD_PIVOT[0]
        py = r.y() + r.height() * HEAD_PIVOT[1]
        dx = self.hover_pos.x() - px
        dy = self.hover_pos.y() - py
        ang = math.degrees(math.atan2(dx, max(8.0, -dy))) * HEAD_GAIN
        self.head_target = max(-HEAD_MAX_DEG, min(HEAD_MAX_DEG, ang))

    def _frame(self):
        """帧驱动：头部角度指数趋近目标 + 呼吸重绘；无动画需求时不重绘。"""
        self._update_head_target()
        if self.reduced_motion:
            # 减少动态效果：头部立即回正（不做平滑过渡），静止后不再重绘
            if self.head_angle == 0.0:
                return
            self.head_angle = 0.0
            self.update()
            return
        k = 1.0 - math.exp(-FRAME_MS / 1000.0 / HEAD_TAU)
        self.head_angle += (self.head_target - self.head_angle) * k
        if abs(self.head_angle - self.head_target) < 0.02:
            self.head_angle = self.head_target
        self.update()

    def _poll_reduced_motion(self):
        rm = query_reduced_motion()
        if rm != self.reduced_motion:
            self.reduced_motion = rm
            if rm:
                self.head_target = 0.0
                self.head_angle = 0.0
                self.anim_kind = None
                self.anim_timer.stop()
            else:
                self.t0 = time.monotonic()   # 呼吸从静止相位平滑起步
            self.update()

    # ---------- 互动动画 ----------
    def play_anim(self):
        """点击时轮流触发：跳跃 → 压扁回弹 → 左右抖动；减少动态效果时跳过。"""
        if self.reduced_motion:
            return
        self.anim_kind = ANIM_KINDS[self.anim_index % len(ANIM_KINDS)]
        self.anim_index += 1
        self.anim_t = 0.0
        self.anim_timer.start()

    def _anim_tick(self):
        self.anim_t += ANIM_TICK_MS / ANIM_DUR[self.anim_kind]
        if self.anim_t >= 1.0:
            self.anim_kind = None
            self.anim_timer.stop()
        self.update()

    def _anim_offsets(self):
        """当前动画帧的绘制参数：(水平偏移, 抬升高度, 宽度系数, 高度系数)。"""
        k, t = self.anim_kind, self.anim_t
        if k == "jump":
            # 抛物线：t=0.5 时到达最高点
            return 0.0, self.pix.height() * 0.30 * 4 * t * (1 - t), 1.0, 1.0
        if k == "squash":
            if t < 0.35:            # 压下去
                sy = 1 - 0.38 * math.sin(t / 0.35 * math.pi / 2)
            else:                   # 弹回来，带轻微过冲
                u = (t - 0.35) / 0.65
                sy = 1 - 0.38 * math.exp(-4 * u) * math.cos(u * 1.5 * math.pi)
            return 0.0, 0.0, 1 + (1 - sy) * 0.6, sy   # 压扁时变宽，近似保体积
        if k == "shake":
            # 衰减正弦：3 个来回，幅度递减
            amp = self.pix.width() * 0.055
            return amp * math.exp(-3 * t) * math.sin(t * 6 * math.pi), 0.0, 1.0, 1.0
        return 0.0, 0.0, 1.0, 1.0

    # ---------- 输入光标跟随 ----------
    def _move_to_input_context(self, context):
        pos = _input_safe_position(context.caret, context.focus,
                                   context.candidate, self.size(), context.screen)
        self.move(pos)

    def _input_on_key(self):
        """Enter or refresh input-follow mode when the foreground exposes a caret."""
        context = query_input_context()
        if context is None:
            return
        if not self.input_follow_active:
            self.input_saved_scale = self.scale
            self.input_saved_foot = QPoint(
                self.x() + self.width() // 2, self.y() + self.height())
            self.input_follow_active = True
            self._set_scale(self.input_saved_scale * INPUT_SCALE_FACTOR)
            self.input_poll_timer.start()
        self._move_to_input_context(context)
        self.input_idle_timer.start(INPUT_IDLE_MS)

    def _input_follow_tick(self):
        """Refresh after the target application has processed the latest key."""
        if not self.input_follow_active:
            return
        context = query_input_context()
        if context is not None:
            self._move_to_input_context(context)

    def _stop_input_follow(self):
        """Leave input mode and restore the exact pre-input scale and foot anchor."""
        self.input_idle_timer.stop()
        self.input_poll_timer.stop()
        if not self.input_follow_active:
            return
        saved_scale = self.input_saved_scale
        saved_foot = QPoint(self.input_saved_foot)
        self.input_follow_active = False
        self.input_saved_scale = None
        self.input_saved_foot = None
        self._set_scale(saved_scale)
        self._apply_geometry(saved_foot.x(), saved_foot.y())
        self.update()

    # ---------- 键盘互动 ----------
    def _set_kb(self, on):
        """开关键盘互动：底部键盘区留白联动增减，脚底位置保持不动。"""
        self.kb_enabled = on
        self._held.clear()
        self._paw_held = [0, 0]
        self._paw_lift = [-1e9, -1e9]
        self._set_scale(self.scale)
        self.update()

    def _on_kb_hook_failed(self):
        """全局钩子安装失败：关闭并禁用键盘互动，避免菜单显示已开启却无效。"""
        self.act_kb.setChecked(False)
        self.act_kb.setEnabled(False)
        self.act_kb.setText("键盘互动（不可用）")

    def _on_global_key(self, vk, key_id):
        """物理按键按下：按 QWERTY 左右分区选脚，未知键交替；自动重复忽略。"""
        self._input_on_key()
        if not self.kb_enabled or self.reduced_motion or key_id in self._held:
            return
        if vk in LEFT_VKS:
            side = 0
        elif vk in RIGHT_VKS:
            side = 1
        else:
            self._paw_alt ^= 1
            side = self._paw_alt
        self._held[key_id] = side
        self._paw_held[side] += 1
        # 抬起时刻至少在按下后 KB_TAP_HOLD_MS，快速敲击也有可见按压段
        self._paw_lift[side] = time.monotonic() + KB_TAP_HOLD_MS / 1000.0
        self.update()

    def _on_global_key_up(self, vk, key_id):
        """物理按键松开：对应脚的按住计数 -1，归零后从抬起时刻开始回弹。"""
        side = self._held.pop(key_id, None)
        if side is None:    # 启动前就按住的键 / 开关切换期间的松键
            return
        self._paw_held[side] -= 1
        if self._paw_held[side] <= 0:
            self._paw_held[side] = 0
            self._paw_lift[side] = max(self._paw_lift[side], time.monotonic())
            self.update()

    def _paw_progress(self, side, now):
        """脚掌按压进度（0 悬停 ~ 1 压在键上）：按住保持压下，松开平滑抬回。"""
        if self._paw_held[side] > 0 or now < self._paw_lift[side]:
            return 1.0
        dt = (now - self._paw_lift[side]) * 1000.0
        if dt < KB_TAP_LIFT_MS:
            u = dt / KB_TAP_LIFT_MS
            return 1.0 - u * u * (3 - 2 * u)   # smoothstep 抬起
        return 0.0

    def _draw_keyboard(self, p):
        """画身前小键盘（固定在地面，不随互动动画位移）；返回键盘高度。"""
        kw = self.pix.width() * 0.62
        kh = self.bottom_pad * 1.35
        kx = (self.width() - kw) / 2
        ky = self.height() - 2 - kh
        kb = QRectF(kx, ky, kw, kh)

        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(45, 47, 56))
        p.setBrush(QColor(70, 72, 82))
        p.drawRoundedRect(kb, kh * 0.18, kh * 0.18)
        # 键帽：3 行小圆角矩形，行间留缝
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(168, 171, 184))
        rows, gap = 3, kh * 0.09
        key_h = (kh - gap * (rows + 1)) / rows
        for r_i in range(rows):
            y = ky + gap + r_i * (key_h + gap)
            n = 10 - r_i          # 下面的行键少一点，略有键盘感
            key_w = (kw - gap * (n + 1)) / n
            for c in range(n):
                x = kx + gap + c * (key_w + gap)
                p.drawRoundedRect(QRectF(x, y, key_w, key_h),
                                  key_h * 0.25, key_h * 0.25)
        return kh

    def _draw_paws(self, p, r, press_px):
        """把从原图裁出的两只脚原位叠回（静止时与身体逐像素重合）；
        敲键时顶端固定、向下拉伸 press_px 像素压到键盘上。"""
        now = time.monotonic()
        for side, (pix, (xf, yf, wf, hf)) in enumerate(
                zip(self.paw_pix, self.paw_fracs)):
            prog = self._paw_progress(side, now)
            rect = QRectF(r.x() + r.width() * xf,
                          r.y() + r.height() * yf,
                          r.width() * wf,
                          r.height() * hf + press_px * prog)
            p.drawPixmap(rect, pix, QRectF(pix.rect()))

    # ---------- 绘制 ----------
    def _layout(self, t=None):
        """当前帧猫咪整体的目标矩形（浮点，亚像素）：脚底锚定 + 动画/呼吸形变。"""
        dx, dy, sx, sy = self._anim_offsets()
        bx, by = self._breath_scales(time.monotonic() if t is None else t)
        tw = self.pix.width() * sx * bx
        th = self.pix.height() * sy * by
        x = (self.width() - tw) / 2 + dx
        y = self.height() - self.bottom_pad - th - 3 - dy
        return QRectF(x, y, tw, th)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = self._layout()
        p.drawPixmap(r, self.body_pix, QRectF(self.body_pix.rect()))
        # 头部层：绕颈部转轴旋转后叠回身体（0° 时逐像素还原原图）
        px = r.x() + r.width() * HEAD_PIVOT[0]
        py = r.y() + r.height() * HEAD_PIVOT[1]
        p.save()
        p.translate(px, py)
        p.rotate(self.head_angle)
        p.translate(-px, -py)
        head_rect = QRectF(r.x() + r.width() * self.head_x_frac, r.y(),
                           r.width() * (1 - self.head_x_frac),
                           r.height() * self.head_h_frac)
        p.drawPixmap(head_rect, self.head_pix, QRectF(self.head_pix.rect()))
        p.restore()
        # 脚已从身体抠出：键盘画在身体前，脚层最后叠回（敲键时压向键盘）
        press_px = 0.0
        if self.kb_enabled:
            press_px = self._draw_keyboard(p) * PAW_PRESS_FRAC
        self._draw_paws(p, r, press_px)

    # ---------- 互动 ----------
    def mousePressEvent(self, e):
        self._stop_input_follow()
        self._reset_idle_timer()
        if e.button() == Qt.LeftButton:
            self.dragging = True
            self._press_pos = e.globalPosition().toPoint()
            self.drag_offset = self._press_pos - self.pos()

    def mouseMoveEvent(self, e):
        self._reset_idle_timer()
        self.hover_pos = e.position().toPoint()
        if self.dragging:
            self.move(e.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.dragging = False
            # 拖拽可能把宠物拖去别的屏幕 / 区域外：丢弃旧目标，停留后按当前屏幕重选
            if self.walk_enabled:
                self.walk_target = None
                self._walk_pos = None
                self._restart_walk_pause()
            # 位移很小视为点击 → 弹气泡 + 轮流触发互动动画
            if self._press_pos is not None and \
               (e.globalPosition().toPoint() - self._press_pos).manhattanLength() < 6:
                self.say(self._pick_quote())
                self.play_anim()
            self._press_pos = None

    def leaveEvent(self, _):
        self.hover_pos = None   # 头部由 _frame 平滑回正

    def contextMenuEvent(self, e):
        self._stop_input_follow()
        self._reset_idle_timer()
        self.menu.exec(e.globalPos())

    def focusOutEvent(self, e):
        self._stop_input_follow()
        super().focusOutEvent(e)

    def _current_screen_rect(self):
        """宠物当前所在屏幕的可用区域；拖到副屏后气泡应按副屏定位。"""
        scr = self.screen() or QApplication.primaryScreen()
        return scr.availableGeometry()

    def say(self, text):
        self.screen_rect = self._current_screen_rect()
        head_y = self.y() + self.height() - self.bottom_pad - self.pix.height()   # 猫头顶
        anchor_x = self.x() + self.width() // 2
        # 窗口顶部距屏幕顶部太近时改到下方（用窗口位置而非猫头顶，
        # 因为 top_pad 留白会让猫头顶始终距屏幕顶有 ~89px，导致贴顶时阈值不触发）
        above = self.y() - 80 > self.screen_rect.top()
        anchor_y = head_y - 6 if above else self.y() + self.height() + 6
        self.bubble.popup(text, anchor_x, anchor_y, above, self.screen_rect)

    # ---------- 语录 / 闲置提醒 ----------
    def _pick_quote(self):
        """随机选一条语录，避免与上一条重复。"""
        q = random.choice([x for x in QUOTES if x != self.last_quote] or QUOTES)
        self.last_quote = q
        return q

    def _reset_idle_timer(self):
        """互动后重新计时；下次闲置提醒的间隔在区间内随机取值。"""
        self.idle_timer.start(random.randint(IDLE_MIN_MS, IDLE_MAX_MS))

    def _idle_chatter(self):
        """闲置到时：弹一条随机语录（拖拽中跳过），并继续计时等下一次。"""
        if not self.dragging:
            self.say(self._pick_quote())
        self._reset_idle_timer()

    # ---------- 滚轮缩放：脚底位置不动 ----------
    def wheelEvent(self, e):
        self._stop_input_follow()
        self._reset_idle_timer()
        dy = e.angleDelta().y()
        if dy == 0:   # 纯横向滚动（触控板/倾斜滚轮）不缩放
            return
        factor = ZOOM_STEP if dy > 0 else 1 / ZOOM_STEP
        new_scale = min(MAX_SCALE, max(MIN_SCALE, self.scale * factor))
        if abs(new_scale - self.scale) < 1e-4:
            return
        self._set_scale(new_scale)
        self.update()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    pet = Pet()
    app.aboutToQuit.connect(pet.key_listener.stop)   # 退出时结束钩子线程
    pet.show()
    sys.exit(app.exec())
