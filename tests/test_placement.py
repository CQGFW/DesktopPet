# -*- coding: utf-8 -*-
"""输入跟随的落位几何：纯函数，不需要 Pet 实例。"""
from PySide6.QtCore import QRect, QSize

from desktoppet import config, placement

PET = QSize(60, 52)
SCREEN = QRect(0, 0, 1280, 720)
CARET = QRect(500, 300, 2, 20)
FOCUS = QRect(450, 280, 220, 45)
CANDIDATE = QRect(470, 325, 280, 80)


def test_avoids_focus_and_candidate_inside_screen():
    pos = placement.safe_position(CARET, FOCUS, CANDIDATE, PET, SCREEN)
    rect = QRect(pos, PET)
    assert not rect.intersects(FOCUS)
    assert not rect.intersects(CANDIDATE)
    assert SCREEN.contains(rect)


def test_wide_candidate_bar_pushes_pet_to_the_side():
    """微信输入法的候选条又宽又贴着光标，只能左右避让。"""
    screen = QRect(0, 0, 864, 316)
    caret = QRect(226, 105, 2, 22)
    candidate = QRect(216, 134, 572, 44)
    pos = placement.safe_position(caret, QRect(0, 0, 864, 316), candidate, PET, screen)
    rect = QRect(pos, PET)
    avoid = candidate.adjusted(-config.INPUT_GAP, -config.INPUT_GAP,
                               config.INPUT_GAP, config.INPUT_GAP)
    assert not rect.intersects(avoid)
    assert rect.right() < candidate.left()
    assert abs(rect.center().y() - caret.center().y()) <= 1


def test_full_page_focus_does_not_banish_pet_to_page_bottom():
    """文档编辑器常把整页暴露为焦点控件；避开整页会把宠物推到页面底部。"""
    focus = QRect(10, 20, 875, 810)
    caret = QRect(142, 104, 2, 26)
    pos = placement.safe_position(caret, focus, None, PET, QRect(0, 0, 906, 855))
    assert pos.y() == caret.bottom() + config.INPUT_UNKNOWN_CANDIDATE_GAP + 1
    assert abs(pos.x() + PET.width() // 2 - caret.center().x()) <= 1


def test_unknown_candidate_lane_is_reserved():
    """有些输入法既不给 IMM 候选矩形也没有可用的 UIA 元素，
    这时要给候选条预留车道，而不是紧贴光标。"""
    pos = placement.safe_position(CARET, FOCUS, None, PET, SCREEN)
    rect = QRect(pos, PET)
    assert rect.top() == CARET.bottom() + config.INPUT_UNKNOWN_CANDIDATE_GAP + 1
    assert not rect.intersects(FOCUS)


def test_screen_corner_clamps_without_overlapping_focus():
    focus = QRect(1200, 680, 79, 39)
    pos = placement.safe_position(QRect(1268, 690, 2, 20), focus, None, PET, SCREEN)
    rect = QRect(pos, PET)
    assert SCREEN.contains(rect)
    assert not rect.intersects(focus)


class TestCandidateScore:
    """候选条判定门槛（窗口枚举与 UIA 探测共用）。"""

    def test_accepts_a_candidate_bar_next_to_the_caret(self):
        caret = QRect(226, 105, 2, 22)
        assert placement.candidate_score(QRect(216, 134, 572, 44), caret) is not None

    def test_rejects_shapes_outside_the_size_window(self):
        caret = QRect(226, 105, 2, 22)
        assert placement.candidate_score(QRect(216, 134, 20, 10), caret) is None
        assert placement.candidate_score(QRect(216, 134, 2000, 44), caret) is None
        assert placement.candidate_score(QRect(216, 134, 572, 400), caret) is None

    def test_rejects_far_away_rectangles(self):
        caret = QRect(226, 105, 2, 22)
        far = placement.CANDIDATE_MAX_GAP + 50
        assert placement.candidate_score(
            QRect(226 + far, 105 + far, 572, 44), caret) is None

    def test_prefers_nearer_then_wider(self):
        caret = QRect(226, 105, 2, 22)
        near = placement.candidate_score(QRect(216, 134, 300, 44), caret)
        far = placement.candidate_score(QRect(216, 220, 300, 44), caret)
        assert near < far
        wide = placement.candidate_score(QRect(216, 134, 572, 44), caret)
        assert wide < near      # 同距离时更宽的更像候选条
