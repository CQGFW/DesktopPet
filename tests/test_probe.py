# -*- coding: utf-8 -*-
"""输入跟随诊断：路径与耗时被记录，报告可读，日志去重。"""
import pytest
from PySide6.QtCore import QRect

from desktoppet import debuglog, ime, input_follow, probe, uia, winapi

CARET = QRect(300, 200, 2, 20)
BAR = QRect(300, 230, 200, 40)


@pytest.fixture(autouse=True)
def clean():
    probe.reset()
    ime.reset_cache()
    ime.take_probe_info()
    yield
    probe.reset()
    ime.reset_cache()
    ime.take_probe_info()


def test_report_before_any_query_is_helpful():
    assert "尚未" in probe.report()


def test_record_query_updates_last_and_stats():
    probe.record_query(result="ok", caret_source="uia", candidate_source="imm",
                       total_ms=3.5, process="notepad.exe")
    probe.record_query(result="fail", caret_source="none", candidate_source="none",
                       total_ms=1.0, process="explorer.exe")
    assert probe.stats["queries"] == 2 and probe.stats["ok"] == 1
    assert probe.stats["caret:uia"] == 1 and probe.stats["candidate:none"] == 1
    assert probe.last["process"] == "explorer.exe"
    text = probe.report()
    assert "探测次数 2，成功 1" in text and "uia=1" in text and "explorer.exe" in text


def test_candidate_probe_records_which_path_hit(monkeypatch):
    monkeypatch.setattr(ime, "wechat_candidate_rect", lambda *a, **k: None)
    monkeypatch.setattr(ime, "imm_candidate_rect", lambda *a: BAR)
    assert ime.candidate_rect(CARET, 1, (), 42) == BAR
    info = ime.take_probe_info()
    assert info["candidate_source"] == "imm"
    assert "wechat_ms" in info and "imm_ms" in info and "uia_cand_ms" not in info
    assert ime.candidate_rect(CARET, 1, (), 42) == BAR      # 命中节流缓存
    assert ime.take_probe_info()["candidate_source"] == "cache"


def test_candidate_probe_reports_none_when_every_path_misses(monkeypatch):
    monkeypatch.setattr(ime, "wechat_candidate_rect", lambda *a, **k: None)
    monkeypatch.setattr(ime, "imm_candidate_rect", lambda *a: None)
    monkeypatch.setattr(uia, "candidate_rect", lambda *a: None)
    assert ime.candidate_rect(CARET, 1, (), 42) is None
    assert ime.take_probe_info()["candidate_source"] == "none"


def test_query_records_failure_reason_when_winapi_is_missing(monkeypatch):
    monkeypatch.setattr(winapi, "configure", lambda: False)
    assert input_follow.query_input_context() is None
    assert probe.last["result"] == "fail" and probe.last["reason"] == "winapi unavailable"
    assert probe.last["total_ms"] >= 0


def test_query_records_a_full_success_path(monkeypatch):
    """用假 user32 走通 GUITHREADINFO 路径，检查诊断字段齐全。"""
    class FakeUser32:
        def GetForegroundWindow(self):
            return 7

        def GetWindowThreadProcessId(self, _hwnd, pid):
            pid._obj.value = 4242
            return 9

        def GetGUIThreadInfo(self, _tid, info):
            info._obj.hwndCaret = 8
            info._obj.hwndFocus = 8
            return 1

    class FakeWindll:
        user32 = FakeUser32()

    monkeypatch.setattr(winapi, "configure", lambda: True)
    monkeypatch.setattr(input_follow.ctypes, "windll", FakeWindll(), raising=False)
    monkeypatch.setattr(winapi, "process_name", lambda pid: "notepad.exe")
    monkeypatch.setattr(winapi, "client_rect_to_screen", lambda h, r: CARET)
    monkeypatch.setattr(winapi, "window_rect", lambda h: QRect(250, 180, 140, 45))
    monkeypatch.setattr(ime, "candidate_rect", lambda *a: BAR)
    ime._PROBE_INFO["candidate_source"] = "wechat"
    context = input_follow.query_input_context()
    assert context is not None and context.candidate == BAR
    assert probe.last["result"] == "ok"
    assert probe.last["caret_source"] == "guithreadinfo"
    assert probe.last["candidate_source"] == "wechat"
    assert probe.last["process"] == "notepad.exe"
    assert probe.last["caret"] == (300, 200, 2, 20)
    assert "gui_ms" in probe.last and "total_ms" in probe.last


def test_log_lines_are_deduplicated(monkeypatch):
    lines = []
    monkeypatch.setattr(debuglog, "enabled", lambda: True)
    monkeypatch.setattr(debuglog, "log", lines.append)
    for _ in range(5):
        probe.record_query(result="ok", caret_source="uia", candidate_source="cache",
                           process="a.exe", total_ms=1.0)
    probe.record_query(result="ok", caret_source="uia", candidate_source="imm",
                       process="a.exe", total_ms=1.0)
    assert len(lines) == 2 and "candidate=imm" in lines[1]


def test_copy_menu_puts_report_on_clipboard(pet, qapp):
    pet._copy_probe_report()
    assert "输入跟随诊断" in qapp.clipboard().text()
    assert pet.bubble.isVisible()
