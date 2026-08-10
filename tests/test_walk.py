# -*- coding: utf-8 -*-
"""自动走动：默认关闭、限定右下 1/4、匀速收敛、各种暂停与清理。"""
import math

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from desktoppet import config


@pytest.fixture
def walker(pet):
    pet.bubble.hide()       # 气泡可见会暂停走动
    return pet


def test_defaults_to_off(walker):
    assert not walker.walk_enabled
    assert not walker.walk_timer.isActive()
    assert walker.walk_target is None


def test_region_is_the_bottom_right_quadrant(walker):
    screen = walker._current_screen_rect()
    region = walker._walk_region()
    assert region.left() == screen.center().x()
    assert region.top() == screen.center().y()
    assert region.right() == screen.right()
    assert region.bottom() == screen.bottom()


def test_enabling_starts_timer_and_picks_a_target(walker):
    walker.act_walk.setChecked(True)
    assert walker.walk_enabled
    assert walker.walk_timer.isActive()
    assert walker.walk_target is not None


def test_targets_always_keep_the_whole_window_inside_the_region(walker):
    walker.act_walk.setChecked(True)
    region = walker._walk_region()
    for _ in range(60):
        walker._pick_walk_target()
        target = walker.walk_target
        assert region.left() <= target.x() - walker.width() // 2
        assert target.x() + walker.width() // 2 <= region.right() + 1
        assert region.top() <= target.y() - walker.height()
        assert target.y() <= region.bottom()


def test_walks_from_outside_the_region_at_a_uniform_speed(walker):
    """从区域外（左上角）出发，也要一步步匀速走到目标并停下。"""
    screen = walker._current_screen_rect()
    walker.act_walk.setChecked(True)
    walker.move(screen.left(), screen.top())
    walker._pick_walk_target()
    target = QPoint(walker.walk_target)

    step_limit = config.WALK_SPEED * config.WALK_TICK_MS / 1000.0 + 1.5
    previous = (walker.x() + walker.width() // 2, walker.y() + walker.height())
    for _ in range(5000):
        walker._walk_tick()
        current = (walker.x() + walker.width() // 2, walker.y() + walker.height())
        assert math.hypot(current[0] - previous[0],
                          current[1] - previous[1]) <= step_limit
        previous = current
        if walker.walk_target is None:
            break

    assert walker.walk_target is None, "must converge to target"
    assert previous == (target.x(), target.y())
    assert walker.walk_pause_timer.isActive(), "must pause before the next target"


@pytest.mark.parametrize("pause", ["dragging", "reduced_motion", "bubble"])
def test_walking_pauses(walker, pause):
    walker.act_walk.setChecked(True)
    region = walker._walk_region()
    walker.walk_target = QPoint(region.center().x(), region.bottom())
    before = (walker.x(), walker.y())

    if pause == "dragging":
        walker.dragging = True
    elif pause == "reduced_motion":
        walker.reduced_motion = True
    elif pause == "bubble":
        walker.bubble.show()

    walker._walk_tick()
    assert (walker.x(), walker.y()) == before


class TestPauseExpiry:
    def test_frozen_while_paused(self, walker):
        walker.act_walk.setChecked(True)
        walker.walk_target = None
        walker.dragging = True
        walker._on_walk_pause_done()
        assert walker.walk_target is None

    def test_picks_again_once_resumed(self, walker):
        walker.act_walk.setChecked(True)
        walker.walk_target = None
        walker._on_walk_pause_done()
        assert walker.walk_target is not None


def test_drag_release_drops_a_possibly_stale_target(walker):
    """拖拽可能把宠物挪去别的屏幕，旧目标必须作废重选。"""
    walker.act_walk.setChecked(True)
    walker._press_pos = QPoint(-10_000, -10_000)   # 位移够大，不触发点击路径
    walker.dragging = True
    walker.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(5, 5),
        QPointF(walker.x() + 5, walker.y() + 5), Qt.LeftButton, Qt.NoButton,
        Qt.NoModifier))
    assert not walker.dragging
    assert walker.walk_target is None and walker._walk_pos is None
    assert walker.walk_pause_timer.isActive()


def test_zoom_reclamps_the_target_into_the_region(walker):
    walker.act_walk.setChecked(True)
    screen = walker._current_screen_rect()
    region = walker._walk_region()
    walker.walk_target = QPoint(screen.left() + 5, screen.top() + 5)  # 区域外
    walker._set_scale(0.5)
    target = walker.walk_target
    assert region.left() <= target.x() <= region.right()
    assert region.top() <= target.y() <= region.bottom()


def test_disabling_stops_everything(walker):
    walker.act_walk.setChecked(True)
    walker.act_walk.setChecked(False)
    assert not walker.walk_enabled
    assert not walker.walk_timer.isActive()
    assert walker.walk_target is None and walker._walk_pos is None
    assert not walker.walk_pause_timer.isActive()
