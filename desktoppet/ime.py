# -*- coding: utf-8 -*-
"""IME 候选框探测：微信输入法窗口 → 传统 IMM CANDIDATEFORM → UI Automation 兜底。

三条路径都很贵（前者全量枚举窗口，后者几十次跨进程 COM 调用），
对外统一经 candidate_rect() 的节流缓存提供。"""
import ctypes
import time

from PySide6.QtCore import QRect

from . import config, debuglog, placement, uia, winapi


WECHAT_IME_PROCESSES = {
    "wetype.exe",
    "wetype_renderer.exe",
    "wetype_server.exe",
    "wetype_service.exe",
    "chsime.exe",
    "textinputhost.exe",
    "ctfmon.exe",
}

_CANDIDATE_CACHE = None   # (deadline, foreground_hwnd, caret_center, rect)


def candidate_form_rect(form):
    """Convert a winapi.CANDIDATEFORM to its screen-space exclusion rectangle."""
    if (form.rcArea.right > form.rcArea.left
            and form.rcArea.bottom > form.rcArea.top):
        return QRect(form.rcArea.left, form.rcArea.top,
                     form.rcArea.right - form.rcArea.left,
                     form.rcArea.bottom - form.rcArea.top)
    return QRect(form.ptCurrentPos.x, form.ptCurrentPos.y,
                 config.INPUT_IME_FALLBACK_W, config.INPUT_IME_FALLBACK_H)


def imm_candidate_rect(hwnd):
    """Read the traditional IMM candidate exclusion area, when one is exposed.

    winapi.CANDIDATEFORM coordinates are already in screen coordinates.  They must
    not be passed through ClientToScreen, unlike winapi.GUITHREADINFO.rcCaret above.
    """
    if not hwnd or not winapi.configure():
        return None
    try:
        imm32 = ctypes.windll.imm32
        himc = imm32.ImmGetContext(hwnd)
        if not himc:
            return None
        try:
            form = winapi.CANDIDATEFORM()
            form.dwIndex = 0
            if not imm32.ImmGetCandidateWindow(himc, 0, ctypes.byref(form)):
                return None
            return candidate_form_rect(form)
        finally:
            imm32.ImmReleaseContext(hwnd, himc)
    except Exception:
        debuglog.exception('imm_candidate_rect')
        return None


def select_wechat_candidate(caret, windows):
    """从枚举到的窗口里挑最像候选条的一个（判定门槛见 placement.candidate_score）。"""
    nearby = []
    for process_name, rect in windows:
        normalized_name = process_name.lower()
        if (normalized_name != "__generic_popup__"
                and normalized_name not in WECHAT_IME_PROCESSES
                and not normalized_name.startswith("wetype_")):
            continue
        score = placement.candidate_score(rect, caret)
        if score is not None:
            nearby.append((score, rect))
    return min(nearby, key=lambda item: item[0])[1] if nearby else None


def wechat_candidate_rect(caret, excluded_hwnds=()):
    if not winapi.configure():
        return None
    windows = []
    seen_hwnds = set()
    recognized_roots = []
    excluded_hwnds = {int(hwnd) for hwnd in excluded_hwnds if hwnd}
    callback_failed = False
    user32 = ctypes.windll.user32

    def inspect(hwnd, allow_generic):
        nonlocal callback_failed
        try:
            hwnd_value = int(hwnd)
            if hwnd_value in seen_hwnds or hwnd_value in excluded_hwnds:
                return True
            seen_hwnds.add(hwnd_value)
            if user32.IsWindowVisible(hwnd):
                process_id = winapi.window_process_id(hwnd)
                if process_id is None or process_id == winapi.own_process_id():
                    return True     # 跳过宠物本体 / 气泡 / 菜单等自身窗口
                process_name = winapi.process_name(process_id)
                normalized_name = (process_name or "").lower()
                if (normalized_name in WECHAT_IME_PROCESSES
                        or normalized_name.startswith("wetype_")):
                    rect = winapi.window_rect(hwnd)
                    if rect is not None:
                        windows.append((process_name, rect))
                    if allow_generic:
                        recognized_roots.append(hwnd)
                elif allow_generic and normalized_name != "":
                    get_long = getattr(user32, "GetWindowLongPtrW", None)
                    if get_long is not None:
                        style = int(get_long(hwnd, winapi.GWL_STYLE))
                        exstyle = int(get_long(hwnd, winapi.GWL_EXSTYLE))
                        if winapi.is_generic_popup_style(style, exstyle):
                            rect = winapi.window_rect(hwnd)
                            if rect is not None:
                                windows.append(("__generic_popup__", rect))
            return True
        except Exception:
            debuglog.exception('wechat_candidate_rect.callback')
            callback_failed = True
            return False

    @winapi.WNDENUMPROC
    def collect_root(hwnd, _):
        return inspect(hwnd, True)

    @winapi.WNDENUMPROC
    def collect_child(hwnd, _):
        return inspect(hwnd, False)

    try:
        if not user32.EnumWindows(collect_root, 0):
            return None
        enum_children = getattr(user32, "EnumChildWindows", None)
        if enum_children is not None:
            for root in recognized_roots:
                if not enum_children(root, collect_child, 0):
                    return None
        if callback_failed:
            return None
        return select_wechat_candidate(caret, windows)
    except Exception:
        debuglog.exception('wechat_candidate_rect')
        return None


def reset_cache():
    global _CANDIDATE_CACHE
    _CANDIDATE_CACHE = None


def discover_candidate(caret, ime_hwnd, excluded_hwnds):
    """按 微信输入法 → IMM → UIA 的顺序探测候选框区域。

    三条路径都很贵（前者要全量枚举窗口，后者要几十次跨进程 UIA 调用），
    只应经 candidate_rect 的节流缓存调用。"""
    candidate = wechat_candidate_rect(caret, excluded_hwnds)
    if candidate is None:
        candidate = imm_candidate_rect(ime_hwnd)
    if candidate is None:
        candidate = uia.candidate_rect(caret)
    return candidate


def candidate_rect(caret, ime_hwnd, excluded_hwnds, foreground):
    """节流候选框探测：候选条一旦弹出会稳定停留数百毫秒，不必每次轮询都重扫。

    宠物位置仍按 config.INPUT_POLL_MS 刷新，这里复用的只是"候选区在哪"这一结论；
    前台窗口切换或光标明显移动时立即失效重探，避免用上过期的避让区域。"""
    global _CANDIDATE_CACHE
    now = time.monotonic()
    center = caret.center()
    key = int(foreground or 0)
    if _CANDIDATE_CACHE is not None:
        deadline, cached_key, cached_center, cached_rect = _CANDIDATE_CACHE
        if (now < deadline and cached_key == key
                and abs(cached_center.x() - center.x()) <= config.INPUT_CANDIDATE_CARET_TOL
                and abs(cached_center.y() - center.y()) <= config.INPUT_CANDIDATE_CARET_TOL):
            return cached_rect
    rect = discover_candidate(caret, ime_hwnd, excluded_hwnds)
    _CANDIDATE_CACHE = (now + config.INPUT_CANDIDATE_TTL, key, center, rect)
    return rect
