# -*- coding: utf-8 -*-
"""输入跟随的落位几何：挑一个屏幕内、不压住输入框与候选条的位置。

纯几何计算，不依赖 Win32 与宠物状态，可独立单测。"""
from PySide6.QtCore import QPoint, QRect

from . import config


def safe_position(caret, focus, candidate, pet_size, screen, gap=config.INPUT_GAP):
    """Choose a screen-contained pet position, preferring below the caret."""
    width, height = pet_size.width(), pet_size.height()
    max_x = screen.right() - width + 1
    max_y = screen.bottom() - height + 1

    def clamp_x(x):
        return max(screen.left(), min(x, max_x))

    def clamp_y(y):
        return max(screen.top(), min(y, max_y))

    avoids = []
    candidate_avoid = None
    if focus is not None and not focus.isNull() and focus.isValid():
        compact_limit = max(config.INPUT_COMPACT_FOCUS_MAX_H,
                            pet_size.height() + gap * 2,
                            caret.height() * 4)
        # 文档编辑器常把整页作为焦点控件；避开整页会把宠物推到屏幕底部。
        # 紧凑输入框避开完整边界，多行编辑区只避开光标本身与 IME 区域。
        if focus.contains(caret.center()) and focus.height() <= compact_limit:
            avoids.append(focus.adjusted(-gap, -gap, gap, gap))
    if candidate is not None and not candidate.isNull() and candidate.isValid():
        candidate_avoid = candidate.adjusted(-gap, -gap, gap, gap)
        avoids.append(candidate_avoid)

    center_x = clamp_x(caret.center().x() - width // 2)
    below_y = caret.bottom() + gap + 1
    if candidate_avoid is None:
        # Modern IMEs may render candidates without exposing a usable window.
        # Reserve their likely lane so the pet does not sit directly on it.
        below_y = caret.bottom() + config.INPUT_UNKNOWN_CANDIDATE_GAP + 1
    preferred_below = QRect(center_x, below_y, width, height)
    for _ in range(len(avoids) + 1):
        probe = QRect(center_x, below_y, width, height)
        hits = [rect for rect in avoids if probe.intersects(rect)]
        if not hits:
            break
        below_y = max(rect.bottom() + 1 for rect in hits)

    if candidate_avoid is not None and preferred_below.intersects(candidate_avoid):
        side_y = caret.center().y() - height // 2
        candidates = [(candidate.left() - gap - width, side_y),
                      (candidate.right() + gap + 1, side_y),
                      (center_x, candidate.bottom() + gap + 1),
                      (center_x, caret.top() - gap - height)]
    else:
        candidates = [(center_x, below_y),
                      (center_x, caret.top() - gap - height),
                      (caret.left() - gap - width,
                       caret.center().y() - height // 2),
                      (caret.right() + gap + 1,
                       caret.center().y() - height // 2)]

    side_y = caret.center().y() - height // 2
    for avoid in avoids:
        candidates.extend([
            (center_x, avoid.top() - height - 1),
            (avoid.left() - width - 1, side_y),
            (avoid.right() + 1, side_y),
            (center_x, avoid.bottom() + 1),
        ])

    for x, y in candidates:
        rect = QRect(clamp_x(x), y, width, height)
        if screen.contains(rect) and not any(rect.intersects(a) for a in avoids):
            return rect.topLeft()

    return QPoint(clamp_x(center_x), clamp_y(below_y))


# IME 候选条的判定门槛：窗口/元素尺寸落在此区间，且与光标的间距不超过
# CANDIDATE_MAX_GAP，才当作候选区。窗口枚举与 UIA 探测两条路径共用同一套阈值。
CANDIDATE_MIN_W, CANDIDATE_MAX_W = 80, 1200
CANDIDATE_MIN_H, CANDIDATE_MAX_H = 24, 180
CANDIDATE_MAX_GAP = 240


def candidate_score(rect, caret):
    """把矩形按"像不像光标旁的候选条"打分。

    返回 (到光标距离的平方, -宽度) 作为排序键——先挑离光标最近的，同距离时
    偏好更宽的（候选条通常比普通弹窗宽）。不满足门槛时返回 None。"""
    if not (CANDIDATE_MIN_W <= rect.width() <= CANDIDATE_MAX_W
            and CANDIDATE_MIN_H <= rect.height() <= CANDIDATE_MAX_H):
        return None
    dx = max(rect.left() - caret.right(), caret.left() - rect.right(), 0)
    dy = max(rect.top() - caret.bottom(), caret.top() - rect.bottom(), 0)
    if dx > CANDIDATE_MAX_GAP or dy > CANDIDATE_MAX_GAP:
        return None
    return (dx * dx + dy * dy, -rect.width())
