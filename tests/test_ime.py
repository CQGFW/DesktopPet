# -*- coding: utf-8 -*-
"""IME 候选框识别：坐标语义、进程/样式筛选、枚举失败兜底、探测节流缓存。"""
import os

from PySide6.QtCore import QPoint, QRect

from desktoppet import ime, winapi

CARET = QRect(226, 105, 2, 22)
BAR = QRect(216, 134, 572, 44)


class TestCandidateFormRect:
    """IMM 的 CANDIDATEFORM 已经是屏幕坐标，不能再过 ClientToScreen。

    夹具刻意用非零的窗口原点，一旦有人误加坐标转换就会被这里抓到。"""

    def test_uses_area_when_present(self):
        form = winapi.CANDIDATEFORM()
        form.rcArea.left, form.rcArea.top = 720, 410
        form.rcArea.right, form.rcArea.bottom = 980, 510
        assert ime.candidate_form_rect(form) == QRect(720, 410, 260, 100)

    def test_falls_back_to_current_pos_when_area_is_empty(self):
        form = winapi.CANDIDATEFORM()
        form.ptCurrentPos.x, form.ptCurrentPos.y = 720, 410
        form.rcArea.left = form.rcArea.right = 720
        form.rcArea.top = form.rcArea.bottom = 410
        assert ime.candidate_form_rect(form).topLeft() == QPoint(720, 410)


class TestSelectWechatCandidate:
    def test_picks_the_bar_nearest_the_caret(self):
        windows = [
            ("wetype_renderer.exe", BAR),
            ("wetype_server.exe", BAR),
            ("wetype_renderer.exe", QRect(1400, 700, 500, 44)),   # 太远
            ("other_overlay.exe", QRect(210, 130, 580, 50)),      # 非输入法进程
        ]
        assert ime.select_wechat_candidate(CARET, windows) == BAR

    def test_rejects_windows_that_are_too_small(self):
        assert ime.select_wechat_candidate(
            CARET, [("wetype_renderer.exe", QRect(216, 134, 20, 10))]) is None

    def test_accepts_every_known_ime_host(self):
        for name in ("wetype.exe", "ChsIME.exe", "textinputhost.exe", "ctfmon.exe"):
            assert ime.select_wechat_candidate(CARET, [(name, BAR)]) == BAR

    def test_accepts_generic_popup_marker(self):
        assert ime.select_wechat_candidate(CARET, [("__generic_popup__", BAR)]) == BAR


class TestGenericPopupStyle:
    def test_accepts_borderless_toolwindow_popup(self):
        assert winapi.is_generic_popup_style(winapi.WS_POPUP, winapi.WS_EX_TOOLWINDOW)

    def test_rejects_titled_window(self):
        assert not winapi.is_generic_popup_style(
            winapi.WS_POPUP | winapi.WS_CAPTION, winapi.WS_EX_TOOLWINDOW)


def test_enumeration_callback_failure_yields_no_candidate(monkeypatch):
    """枚举回调里抛异常必须整体作废，不能返回半份窗口列表。"""

    class FailingUser32:
        def IsWindowVisible(self, _hwnd):
            raise RuntimeError("callback failure")

        def EnumWindows(self, callback, _lparam):
            callback(123, 0)
            return True

    monkeypatch.setattr(winapi, "configure", lambda: True)
    monkeypatch.setattr(ime.ctypes.windll, "user32", FailingUser32())
    assert ime.wechat_candidate_rect(CARET) is None


def test_own_process_id_matches_this_process():
    """宠物自己的气泡也是无边框置顶分层窗口，必须靠 PID 排除掉。"""
    assert winapi.own_process_id() == os.getpid()


class TestCandidateThrottle:
    """候选条一旦弹出会稳定停留数百毫秒，没必要每次轮询都重扫窗口 / 打 UIA。"""

    def _counting_discover(self, monkeypatch, result=None):
        calls = []
        monkeypatch.setattr(
            ime, "discover_candidate",
            lambda caret, ime_hwnd, excluded: (calls.append(caret.center()), result)[1])
        ime.reset_cache()
        return calls

    def test_reuses_result_within_ttl(self, monkeypatch):
        calls = self._counting_discover(monkeypatch, BAR)
        for _ in range(20):
            assert ime.candidate_rect(CARET, 1, (), 42) == BAR
        assert len(calls) == 1

    def test_caches_the_absence_of_a_candidate_too(self, monkeypatch):
        """无候选框是最常见的情况（敲英文时），这条路径更需要缓存。"""
        calls = self._counting_discover(monkeypatch, None)
        for _ in range(10):
            assert ime.candidate_rect(CARET, 1, (), 42) is None
        assert len(calls) == 1

    def test_small_caret_movement_still_reuses(self, monkeypatch):
        from desktoppet import config
        calls = self._counting_discover(monkeypatch, BAR)
        ime.candidate_rect(CARET, 1, (), 42)
        ime.candidate_rect(CARET.translated(config.INPUT_CANDIDATE_CARET_TOL, 0),
                           1, (), 42)
        assert len(calls) == 1

    def test_large_caret_movement_reprobes(self, monkeypatch):
        from desktoppet import config
        calls = self._counting_discover(monkeypatch, BAR)
        ime.candidate_rect(CARET, 1, (), 42)
        ime.candidate_rect(CARET.translated(config.INPUT_CANDIDATE_CARET_TOL + 1, 0),
                           1, (), 42)
        assert len(calls) == 2

    def test_foreground_switch_reprobes(self, monkeypatch):
        calls = self._counting_discover(monkeypatch, BAR)
        ime.candidate_rect(CARET, 1, (), 42)
        ime.candidate_rect(CARET, 1, (), 99)
        assert len(calls) == 2

    def test_expired_ttl_reprobes(self, monkeypatch):
        calls = self._counting_discover(monkeypatch, BAR)
        ime.candidate_rect(CARET, 1, (), 42)
        deadline, key, center, rect = ime._CANDIDATE_CACHE
        monkeypatch.setattr(ime, "_CANDIDATE_CACHE", (deadline - 10.0, key, center, rect))
        ime.candidate_rect(CARET, 1, (), 42)
        assert len(calls) == 2

    def test_reset_cache_forces_reprobe(self, monkeypatch):
        calls = self._counting_discover(monkeypatch, BAR)
        ime.candidate_rect(CARET, 1, (), 42)
        ime.reset_cache()
        ime.candidate_rect(CARET, 1, (), 42)
        assert len(calls) == 2
