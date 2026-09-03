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


class TestFacing:
    def _walk_towards(self, walker, x):
        walker._set_walk(True)
        walker.walk_target = QPoint(x, walker.y() + walker.height())
        walker._walk_pos = None
        walker._walk_tick()

    def test_defaults_to_facing_right(self, walker):
        assert walker.facing == 1

    def test_turns_left_when_walking_left(self, walker):
        self._walk_towards(walker, walker.x() - 400)
        assert walker.facing == -1

    def test_turns_back_right_when_walking_right(self, walker):
        self._walk_towards(walker, walker.x() - 400)
        self._walk_towards(walker, walker.x() + 400)
        assert walker.facing == 1

    def test_vertical_move_keeps_current_facing(self, walker):
        self._walk_towards(walker, walker.x() - 400)
        foot_x = walker.x() + walker.width() // 2
        walker.walk_target = QPoint(foot_x, walker.y() + walker.height() - 50)
        walker._walk_pos = None
        walker._walk_tick()
        assert walker.facing == -1

    def test_disabling_walk_restores_original_facing(self, walker):
        self._walk_towards(walker, walker.x() - 400)
        walker._set_walk(False)
        assert walker.facing == 1

    @staticmethod
    def _opaque_span(img):
        """不透明像素的横向范围 (left, right)，用于判断画面是否左右翻了。"""
        xs = [x for x in range(img.width())
              if any(img.pixelColor(x, y).alpha() > 40 for y in range(0, img.height(), 4))]
        return xs[0], xs[-1]

    def test_mirrored_frame_renders_and_is_a_mirror_image(self, walker):
        walker.reduced_motion = True     # 冻结呼吸，两帧几何一致
        walker.hover_pos = None
        walker.head_angle = 0.0
        normal = walker.grab().toImage()
        walker.facing = -1
        mirrored = walker.grab().toImage()
        assert not mirrored.isNull() and mirrored.size() == normal.size()
        nl, nr = self._opaque_span(normal)
        ml, mr = self._opaque_span(mirrored)
        w = normal.width() - 1
        assert abs(ml - (w - nr)) <= 2 and abs(mr - (w - nl)) <= 2, ((nl, nr), (ml, mr))
        assert nl != w - nr, "sprite must be asymmetric for this test to mean anything"

    def test_head_pivot_mirrors_with_the_body(self, walker):
        """镜像后鼠标在猫头视觉右侧，仍应让头向右（正角）倾。"""
        walker.facing = -1
        r = walker._cat_rect()
        walker.hover_pos = QPoint(int(r.x() + r.width() * 0.2), int(r.y() + r.height() * 0.2))
        walker._update_head_target()
        left_of_mirrored_pivot = walker.head_target
        walker.hover_pos = QPoint(int(r.x() + r.width() * 0.5), int(r.y() + r.height() * 0.2))
        walker._update_head_target()
        assert left_of_mirrored_pivot < 0 < walker.head_target
