# -*- coding: utf-8 -*-
"""呼吸、头部跟随、点击动画，以及系统"减少动态效果"下的降级行为。"""
import math

from PySide6.QtCore import QPoint

from desktoppet import config, winapi


def hover_at(pet, fx, fy):
    """把鼠标放在猫身矩形的相对位置 (fx, fy)，返回算出的头部目标角。"""
    rect = pet._cat_rect()
    pet.hover_pos = QPoint(round(rect.x() + rect.width() * fx),
                           round(rect.y() + rect.height() * fy))
    pet._update_head_target()
    return pet.head_target


class TestIdle:
    def test_v1_walk_state_is_gone(self, pet):
        assert not hasattr(pet, "vx") and not hasattr(pet, "behave")

    def test_idle_frames_do_not_move_the_window(self, pet):
        before = (pet.x(), pet.y())
        for _ in range(200):
            pet._frame()
        assert (pet.x(), pet.y()) == before


class TestBreathing:
    def test_amplitude_reaches_but_never_exceeds_the_configured_range(self, pet):
        ys = [pet._breath_scales(pet.t0 + i * 0.033)[1] for i in range(240)]
        assert max(ys) <= 1 + config.BREATH_AMP_Y + 1e-9
        assert min(ys) >= 1 - config.BREATH_AMP_Y - 1e-9
        assert max(ys) > 1 + config.BREATH_AMP_Y * 0.95
        assert min(ys) < 1 - config.BREATH_AMP_Y * 0.95

    def test_is_continuous_across_frames(self, pet):
        ys = [pet._breath_scales(pet.t0 + i * 0.033)[1] for i in range(240)]
        for a, b in zip(ys, ys[1:]):
            assert abs(b - a) < 0.002, "breathing must be continuous (no frame jump)"

    def test_keeps_feet_and_centre_anchored(self, pet):
        for i in range(0, 240, 17):
            rect = pet._layout(pet.t0 + i * 0.033)
            assert abs(rect.bottom() - (pet.height() - pet.bottom_pad - 3)) < 1e-6
            assert abs(rect.center().x() - pet.width() / 2) < 1e-6


class TestHeadFollow:
    def test_turns_towards_the_mouse(self, pet):
        assert hover_at(pet, 0.90, 0.10) > 2
        assert hover_at(pet, 0.10, 0.10) < -2

    def test_clamps_at_the_maximum_angle(self, pet):
        assert hover_at(pet, 0.99, 0.95) == config.HEAD_MAX_DEG
        assert hover_at(pet, 0.01, 0.95) == -config.HEAD_MAX_DEG

    def test_stays_straight_above_the_pivot(self, pet):
        assert abs(hover_at(pet, 0.66, 0.05)) < 1.5

    def test_approach_is_smooth_and_monotonic(self, pet):
        rect = pet._cat_rect()
        pet.hover_pos = QPoint(round(rect.x() + rect.width() * 0.9),
                               round(rect.y() + rect.height() * 0.2))
        angles = []
        for _ in range(120):
            pet._frame()
            angles.append(pet.head_angle)
        target = pet.head_target
        assert abs(angles[-1] - target) < 0.05
        assert all(b >= a - 1e-9 for a, b in zip(angles, angles[1:]))
        step_max = max(abs(b - a) for a, b in zip(angles, angles[1:]))
        assert step_max < target * 0.35, "no snapping, smooth approach"

    def test_returns_to_centre_when_the_mouse_leaves(self, pet):
        hover_at(pet, 0.9, 0.2)
        for _ in range(150):
            pet._frame()
        pet.hover_pos = None
        for _ in range(150):
            pet._frame()
        assert abs(pet.head_angle) < 0.05

    def test_padding_area_does_not_trigger_a_turn(self, pet):
        pet.hover_pos = QPoint(2, 2)
        pet._update_head_target()
        assert pet.head_target == 0.0

    def test_no_turn_while_dragging(self, pet):
        pet.dragging = True
        assert hover_at(pet, 0.9, 0.2) == 0.0

    def test_rotated_head_stays_inside_the_window(self, pet):
        rect = pet._layout(pet.t0)
        px = rect.x() + rect.width() * config.HEAD_PIVOT[0]
        py = rect.y() + rect.height() * config.HEAD_PIVOT[1]
        left = rect.x() + rect.width() * pet.head_x_frac
        bottom = rect.y() + rect.height() * pet.head_h_frac
        corners = [(left, rect.y()), (rect.right(), rect.y()),
                   (left, bottom), (rect.right(), bottom)]
        for deg in (config.HEAD_MAX_DEG, -config.HEAD_MAX_DEG):
            a = math.radians(deg)
            for cx, cy in corners:
                x = px + (cx - px) * math.cos(a) - (cy - py) * math.sin(a)
                y = py + (cx - px) * math.sin(a) + (cy - py) * math.cos(a)
                assert -1 <= x <= pet.width() + 1 and -1 <= y <= pet.height() + 1


class TestReducedMotion:
    def test_breath_and_head_are_frozen(self, pet):
        pet.reduced_motion = True
        assert pet._breath_scales(pet.t0 + 1.7) == (1.0, 1.0)
        assert hover_at(pet, 0.9, 0.2) == 0.0

    def test_click_animation_is_skipped(self, pet):
        pet.reduced_motion = True
        pet.play_anim()
        assert pet.anim_kind is None and not pet.anim_timer.isActive()

    def test_bubble_still_shows(self, pet):
        pet.reduced_motion = True
        pet.say("降级模式也要说话")
        assert pet.bubble.isVisible()

    def test_head_snaps_to_zero_instead_of_easing(self, pet):
        pet.reduced_motion = True
        pet.head_angle = 7.5
        pet._frame()
        assert pet.head_angle == 0.0

    def test_poll_path_also_snaps_head_to_zero(self, pet, monkeypatch):
        pet.head_angle = 5.0
        monkeypatch.setattr(winapi, "query_reduced_motion", lambda: True)
        pet._poll_reduced_motion()
        assert pet.reduced_motion
        assert pet.head_angle == 0.0 and pet.head_target == 0.0


class TestClickAnimations:
    def test_kinds_cycle_in_order(self, pet):
        kinds = []
        for _ in range(4):
            pet.play_anim()
            kinds.append(pet.anim_kind)
            pet.anim_kind = None
            pet.anim_timer.stop()
        assert kinds == ["jump", "squash", "shake", "jump"]

    def _offsets_at(self, pet, kind, t):
        pet.anim_kind, pet.anim_t = kind, t
        return pet._anim_offsets()

    def test_jump_peaks_at_midpoint(self, pet):
        dx, dy, sx, sy = self._offsets_at(pet, "jump", 0.5)
        assert abs(dy - pet.pix.height() * 0.30) < 1
        assert dx == 0 and sx == sy == 1.0

    def test_squash_widens_while_flattening(self, pet):
        _, _, sx, sy = self._offsets_at(pet, "squash", 0.35)
        assert abs(sy - 0.62) < 0.01 and abs(sx - 1.228) < 0.01

    def test_squash_stays_within_the_side_padding(self, pet):
        assert pet.pix.width() * 1.228 <= pet.pix.width() + 2 * pet.side_pad

    def test_shake_stays_within_the_side_padding(self, pet):
        peak = max(abs(self._offsets_at(pet, "shake", t / 100)[0])
                   for t in range(0, 34))
        assert peak <= pet.side_pad

    def test_animation_finishes_and_resets(self, pet):
        pet.anim_kind = None
        pet.play_anim()
        for _ in range(200):
            pet._anim_tick()
            if pet.anim_kind is None:
                break
        assert pet.anim_kind is None and not pet.anim_timer.isActive()
        assert pet._anim_offsets() == (0.0, 0.0, 1.0, 1.0)
