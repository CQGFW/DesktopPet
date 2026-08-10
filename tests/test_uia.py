# -*- coding: utf-8 -*-
"""UI Automation 层的降级契约。

这两条路径在开发机上很难真正跑通（需要真实的前台插入符与 IME 候选条），
但它们必须在拿不到 UIA 客户端时"安静地返回空值"而不是抛异常——
一旦抛出，异常会被 query_input_context 的兜底吞掉，表现为输入跟随整个失灵。"""
from PySide6.QtCore import QRect

from desktoppet import uia


def test_input_rects_degrades_to_a_none_pair(monkeypatch):
    monkeypatch.setattr(uia, "client", lambda: None)
    assert uia.input_rects() == (None, None)


def test_candidate_rect_degrades_to_none(monkeypatch):
    monkeypatch.setattr(uia, "client", lambda: None)
    assert uia.candidate_rect(QRect(10, 10, 2, 20)) is None


def test_candidate_rect_rejects_an_invalid_caret(monkeypatch):
    monkeypatch.setattr(uia, "client", lambda: object())
    assert uia.candidate_rect(None) is None
    assert uia.candidate_rect(QRect()) is None


def test_shutdown_is_idempotent_and_safe_without_init():
    uia.shutdown()
    uia.shutdown()
    assert uia._UIA_CLIENT is None
    assert uia._COM_OWNED is False
