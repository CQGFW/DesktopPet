# -*- coding: utf-8 -*-
"""惯性抛掷：释放速度采样、屏幕内回弹积分、起飞判定、各种中止路径与撞击动画。"""
import math
import random

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QContextMenuEvent, QMouseEvent, QWheelEvent

from desktoppet import config, fling, input_follow, winapi

# ---------- 纯物理：速度采样 ----------

WINDOW, HOLD = 0.12, 0.08


def tracker():
    return fling.VelocityTracker(WINDOW, HOLD)


def feed(tr, vx, vy, start=(0.0, 100.0, 100.0), steps=10, dt=0.008):
    """从 start=(t, x, y) 起以恒定速度 (vx, vy) 喂 steps 个样本，返回轨迹上的下一点
    （可作为下一段的起点或松手点）。"""
    t, x, y = start
    for _ in range(steps):
        tr.add(t, x, y)
        t += dt
        x += vx * dt
        y += vy * dt
    return t, x, y


class TestVelocityTracker:
    def test_empty_tracker_gives_zero(self):
        assert tracker().velocity(1.0, 0, 0) == (0.0, 0.0)

    def test_constant_motion_is_measured_exactly(self):
        tr = tracker()
        t, x, y = feed(tr, 1500.0, -600.0)
        vx, vy = tr.velocity(t, x, y)
        assert abs(vx - 1500.0) < 1e-6 and abs(vy + 600.0) < 1e-6

    def test_slow_drag_stays_slow(self):
        tr = tracker()
        t, x, y = feed(tr, 120.0, 0.0)
        vx, vy = tr.velocity(t, x, y)
        assert math.hypot(vx, vy) < config.FLING_MIN_SPEED

    def test_pause_longer_than_hold_zeroes_velocity(self):
        """拖快了再停住不动，然后松手：是「放下」，不是「甩出」。"""
        tr = tracker()
        t, x, y = feed(tr, 2000.0, 0.0)
        assert tr.velocity(t + HOLD + 0.001, x, y) == (0.0, 0.0)

    def test_short_pause_decays_but_keeps_velocity(self):
        """停顿不足阈值：分母带上停顿时长，速度按比例衰减而不是硬切。"""
        tr = tracker()
        t, x, y = feed(tr, 2000.0, 0.0)
        prompt = tr.velocity(t, x, y)[0]
        paused = tr.velocity(t + HOLD * 0.5, x, y)[0]
        assert 0 < paused < prompt

    def test_only_the_recent_window_counts(self):
        """先向左拖很久，最后一段向右甩：窗口内全是向右的样本，速度就是向右的。"""
        tr = tracker()
        point = feed(tr, -1500.0, 0.0, steps=60)                 # 480ms 向左
        t, x, y = feed(tr, 1500.0, 0.0, start=point, steps=16)   # 最后 128ms 向右
        vx, _ = tr.velocity(t, x, y)
        assert abs(vx - 1500.0) < 1e-6

    def test_direction_reversal_inside_window_averages_out(self):
        """窗口内先右后左回到原点：平均速度接近 0，不会只看最后一段就误判为甩出。"""
        tr = tracker()
        point = feed(tr, 1500.0, 0.0, steps=6)
        t, x, y = feed(tr, -1500.0, 0.0, start=point, steps=6)
        vx, _ = tr.velocity(t, x, y)
        assert abs(vx) < 1e-6

    def test_too_short_a_span_is_noise(self):
        """按下和松开之间没有真实移动却相隔很远（合成事件）：不能算出天文数字。"""
        tr = tracker()
        tr.add(0.0, 0, 0)
        assert tr.velocity(0.005, 50, 50) == (0.0, 0.0)
        vx, vy = tr.velocity(0.05, 50, 50)
        assert vx > 0 and vy > 0

    def test_press_sample_anchors_an_immediate_flick(self):
        tr = tracker()
        tr.add(0.0, 0, 0)                     # 按下
        tr.add(0.02, 40, 0)
        vx, _ = tr.velocity(0.04, 80, 0)
        assert abs(vx - 2000.0) < 1e-6

    def test_samples_are_pruned_and_reset(self):
        tr = tracker()
        for i in range(5000):
            tr.add(i * 0.001, i, 0)
        assert len(tr) <= (WINDOW + HOLD) / 0.001 + 2
        tr.reset()
        assert len(tr) == 0


def test_limit_speed_keeps_direction():
    vx, vy = fling.limit_speed(3000.0, 4000.0, 1000.0)
    assert abs(math.hypot(vx, vy) - 1000.0) < 1e-9
    assert abs(vx / vy - 0.75) < 1e-9
    assert fling.limit_speed(30.0, 40.0, 1000.0) == (30.0, 40.0)
    assert fling.limit_speed(0.0, 0.0, 1000.0) == (0.0, 0.0)


# ---------- 纯物理：积分与回弹 ----------

DT = config.FLING_TICK_MS / 1000.0
BOUNDS = fling.Bounds.normalized(-30, 1600, -80, 700)


def params(**overrides):
    base = dict(friction=config.FLING_FRICTION,
                ground_friction=config.FLING_GROUND_FRICTION,
                gravity=config.FLING_GRAVITY,
                restitution_x=config.FLING_RESTITUTION_X,
                restitution_y=config.FLING_RESTITUTION_Y,
                bounce_min_speed=config.FLING_BOUNCE_MIN_SPEED,
                stop_speed=config.FLING_STOP_SPEED)
    base.update(overrides)
    return fling.Params(**base)


def simulate(body, bounds=BOUNDS, p=None, limit_s=30.0):
    """一直积分到停下；返回 (轨迹, 碰撞列表, 用时秒)。"""
    p = p or params()
    trail, hits, t = [body], [], 0.0
    while not fling.settled(body, bounds, p):
        body, hs = fling.step(body, bounds, DT, p)
        trail.append(body)
        hits.extend(hs)
        t += DT
        assert t <= limit_s, "must settle"
    return trail, hits, t


class TestStep:
    def test_gravity_pulls_down_and_friction_slows(self):
        body = fling.Body(500, 300, 1000, 0)
        nxt, hits = fling.step(body, BOUNDS, DT, params())
        assert hits == []
        assert 0 < nxt.vx < 1000 and nxt.vy > 0
        assert nxt.x > body.x and nxt.y > body.y

    def test_friction_is_exponential_in_dt(self):
        body = fling.Body(500, 300, 1000, 0)
        nxt, _ = fling.step(body, BOUNDS, DT, params(gravity=0))
        assert abs(nxt.vx - 1000 * math.exp(-config.FLING_FRICTION * DT)) < 1e-9

    @pytest.mark.parametrize("wall, start, vel, axis, edge, coef", [
        (fling.LEFT, (BOUNDS.x_min + 5, 300), (-1200, 0), "x", BOUNDS.x_min,
         config.FLING_RESTITUTION_X),
        (fling.RIGHT, (BOUNDS.x_max - 5, 300), (1200, 0), "x", BOUNDS.x_max,
         config.FLING_RESTITUTION_X),
        (fling.TOP, (500, BOUNDS.y_min + 5), (0, -1200), "y", BOUNDS.y_min,
         config.FLING_RESTITUTION_Y),
        (fling.BOTTOM, (500, BOUNDS.y_max - 5), (0, 1200), "y", BOUNDS.y_max,
         config.FLING_RESTITUTION_Y),
    ])
    def test_wall_clamps_reverses_and_damps(self, wall, start, vel, axis, edge, coef):
        p = params(gravity=0)
        body = fling.Body(*start, *vel)
        nxt, hits = fling.step(body, BOUNDS, DT, p)
        assert getattr(nxt, axis) == edge
        assert [h[0] for h in hits] == [wall]
        incoming = abs(vel[0] if axis == "x" else vel[1]) * math.exp(-p.friction * DT)
        assert abs(hits[0][1] - incoming) < 1e-9
        v_after = nxt.vx if axis == "x" else nxt.vy
        v_before = vel[0] if axis == "x" else vel[1]
        assert v_after * v_before < 0, "must reverse"
        assert abs(abs(v_after) - incoming * coef) < 1e-9

    def test_corner_reports_both_walls(self):
        body = fling.Body(BOUNDS.x_max - 3, BOUNDS.y_max - 3, 1500, 1500)
        _, hits = fling.step(body, BOUNDS, DT, params())
        assert {h[0] for h in hits} == {fling.RIGHT, fling.BOTTOM}

    def test_resting_on_a_wall_moving_away_is_not_a_hit(self):
        body = fling.Body(BOUNDS.x_min, 300, 400, 0)
        nxt, hits = fling.step(body, BOUNDS, DT, params(gravity=0))
        assert hits == [] and nxt.vx > 0 and nxt.x > BOUNDS.x_min

    def test_position_never_leaves_bounds(self):
        rng = random.Random(7)
        for _ in range(40):
            ang, speed = rng.uniform(0, 2 * math.pi), rng.uniform(500, config.FLING_MAX_SPEED)
            body = fling.Body(rng.uniform(BOUNDS.x_min, BOUNDS.x_max),
                              rng.uniform(BOUNDS.y_min, BOUNDS.y_max),
                              speed * math.cos(ang), speed * math.sin(ang))
            trail, _, t = simulate(body)
            for b in trail:
                assert BOUNDS.x_min <= b.x <= BOUNDS.x_max
                assert BOUNDS.y_min <= b.y <= BOUNDS.y_max
            assert t * 1000 < config.FLING_MAX_DURATION_MS

    def test_settles_on_the_ground_within_the_time_limit(self):
        trail, hits, t = simulate(fling.Body(500, 100, 2000, -800))
        last = trail[-1]
        assert last.y == BOUNDS.y_max and last.speed < config.FLING_STOP_SPEED
        assert any(h[0] == fling.BOTTOM for h in hits)
        assert t * 1000 < config.FLING_MAX_DURATION_MS

    def test_bounce_heights_decay_and_micro_bounces_snap_to_the_ground(self):
        trail, hits, _ = simulate(fling.Body(500, 100, 0, 1500))
        floor = [h[1] for h in hits if h[0] == fling.BOTTOM]
        assert 2 <= len(floor) < 15, "a handful of hops, then it rests"
        assert all(b > a for a, b in zip(floor[1:], floor)), "each bounce weaker"
        assert trail[-1].y == BOUNDS.y_max and trail[-1].vy == 0.0

    def test_ground_friction_stops_a_slide(self):
        p = params()
        body = fling.Body(200, BOUNDS.y_max, 1500, 0)
        trail, hits, t = simulate(body, p=p)
        assert all(h[0] != fling.BOTTOM for h in hits), "sliding, not bouncing"
        assert trail[-1].x < BOUNDS.x_max, "must stop before the far wall"
        assert t < 3.0

    def test_mid_air_slow_point_is_not_settled(self):
        """抛物线顶点速度很低，但有重力就不算停下。"""
        p = params()
        body = fling.Body(500, 300, 0, 0)
        assert not fling.settled(body, BOUNDS, p)
        assert fling.settled(fling.Body(500, BOUNDS.y_max, 0, 0), BOUNDS, p)

    def test_without_gravity_it_settles_anywhere(self):
        p = params(gravity=0)
        trail, hits, _ = simulate(fling.Body(500, 300, 900, 0), p=p)
        assert trail[-1].y == 300 and hits == []

    def test_degenerate_axis_pins_and_zeroes_velocity(self):
        bounds = fling.Bounds.normalized(100, 50, 0, 700)
        assert bounds.x_min == bounds.x_max == 75
        nxt, hits = fling.step(fling.Body(75, 300, 2000, 0), bounds, DT, params())
        assert nxt.x == 75 and nxt.vx == 0 and hits == []

    def test_bounds_clamp(self):
        assert BOUNDS.clamp(-999, 999) == (BOUNDS.x_min, BOUNDS.y_max)
        assert BOUNDS.clamp(10, 10) == (10, 10)


# ---------- Mixin：鼠标驱动 ----------

def mouse(pet, kind, gx, gy, button=Qt.LeftButton):
    buttons = Qt.LeftButton if kind == QEvent.Type.MouseMove else (
        Qt.LeftButton if kind == QEvent.Type.MouseButtonPress else Qt.NoButton)
    ev = QMouseEvent(kind, QPointF(gx - pet.x(), gy - pet.y()), QPointF(gx, gy),
                     button, buttons, Qt.NoModifier)
    if kind == QEvent.Type.MouseButtonPress:
        pet.mousePressEvent(ev)
    elif kind == QEvent.Type.MouseMove:
        pet.mouseMoveEvent(ev)
    else:
        pet.mouseReleaseEvent(ev)


@pytest.fixture
def clock(pet):
    """可控的采样时钟：返回一个单元素列表，改它的值即推进时间。"""
    now = [10.0]
    pet._fling_clock = lambda: now[0]
    return now


def drag(pet, clock, vx, vy, steps=12, dt=0.01, pause=0.0):
    """从宠物窗口内按下，以速度 (vx, vy) 拖 steps 步，停顿 pause 秒后松手。返回松手点。"""
    gx, gy = pet.x() + 20.0, pet.y() + 20.0
    mouse(pet, QEvent.Type.MouseButtonPress, gx, gy)
    for _ in range(steps):
        clock[0] += dt
        gx += vx * dt
        gy += vy * dt
        mouse(pet, QEvent.Type.MouseMove, round(gx), round(gy))
    clock[0] += pause
    mouse(pet, QEvent.Type.MouseButtonRelease, round(gx), round(gy))
    return round(gx), round(gy)


def run_until_stopped(pet):
    limit = config.FLING_MAX_DURATION_MS // config.FLING_TICK_MS + 2
    for _ in range(limit):
        if not pet.fling_active:
            return
        pet._fling_tick()
    assert not pet.fling_active


class TestThrowDetection:
    def test_gentle_drag_just_drops_the_pet(self, pet, clock):
        gx, gy = drag(pet, clock, 150, 0)
        assert not pet.fling_active and not pet.fling_timer.isActive()
        assert (pet.x() + 20, pet.y() + 20) == (gx, gy)

    def test_fast_flick_starts_a_fling_with_the_measured_velocity(self, pet, clock):
        drag(pet, clock, 1800, -400)
        assert pet.fling_active and pet.fling_timer.isActive()
        assert pet.fling_timer.interval() == config.FLING_TICK_MS
        assert abs(pet._fling_body.vx - 1800) < 60 and abs(pet._fling_body.vy + 400) < 60

    def test_hover_before_release_drops_instead_of_flinging(self, pet, clock):
        drag(pet, clock, 1800, 0, pause=config.FLING_HOLD_MS / 1000.0 + 0.05)
        assert not pet.fling_active

    def test_speed_at_the_threshold_is_the_boundary(self, pet, clock):
        drag(pet, clock, config.FLING_MIN_SPEED * 0.9, 0)
        assert not pet.fling_active
        drag(pet, clock, config.FLING_MIN_SPEED * 1.1, 0)
        assert pet.fling_active

    def test_initial_speed_is_capped(self, pet, clock):
        drag(pet, clock, 9000, 9000)
        assert pet.fling_active
        assert pet._fling_body.speed <= config.FLING_MAX_SPEED + 1e-6
        assert abs(pet._fling_body.vx - pet._fling_body.vy) < 1e-6, "direction kept"

    def test_click_never_flings(self, pet, clock):
        pet.bubble.hide()
        gx, gy = pet.x() + 20, pet.y() + 20
        mouse(pet, QEvent.Type.MouseButtonPress, gx, gy)
        clock[0] += 0.05
        mouse(pet, QEvent.Type.MouseButtonRelease, gx + 2, gy + 2)
        assert not pet.fling_active and pet.bubble.isVisible()

    def test_release_without_a_press_is_harmless(self, pet, clock):
        pet.dragging = True
        mouse(pet, QEvent.Type.MouseButtonRelease, pet.x() + 300, pet.y() + 300)
        assert not pet.fling_active and not pet.dragging

    def test_reduced_motion_disables_flinging(self, pet, clock):
        pet.reduced_motion = True
        drag(pet, clock, 2000, 0)
        assert not pet.fling_active

    def test_each_drag_starts_sampling_afresh(self, pet, clock):
        """上一次的高速样本不能影响下一次的判定：按下时必须清空采样。"""
        for i in range(6):                     # 紧贴按下时刻之前的一段高速轨迹
            pet._fling_tracker.add(clock[0] - 0.05 + i * 0.01, 2000 * i * 0.01, 0)
        drag(pet, clock, 100, 0, steps=8)      # 慢拖 8px：超过点击阈值，走松手判定
        assert not pet.fling_active


# ---------- Mixin：飞行、停止与复位 ----------

def cat_inside_screen(pet):
    screen, cat = pet._current_screen_rect(), pet._cat_rect()
    return (screen.left() <= pet.x() + cat.left()
            and pet.x() + cat.left() + cat.width() <= screen.right() + 1
            and screen.top() <= pet.y() + cat.top()
            and pet.y() + pet.height() <= screen.bottom() + 1)


class TestFlight:
    def test_bounds_let_the_visible_cat_touch_the_screen_edges(self, pet):
        screen, cat = pet._current_screen_rect(), pet._cat_rect()
        b = pet._fling_bounds_now()
        assert b.x_min == screen.left() - cat.left()
        assert b.x_max == screen.right() + 1 - (cat.left() + cat.width())
        assert b.y_min == screen.top() - cat.top()
        assert b.y_max == screen.bottom() + 1 - pet.height()
        assert b.x_min < b.x_max and b.y_min < b.y_max

    def test_ticks_move_the_window_then_settle_inside_the_screen(self, pet):
        pet.bubble.hide()
        pet.idle_timer.stop()
        start = (pet.x(), pet.y())
        pet._start_fling(1600, -900)
        assert pet.idle_timer.isActive()
        pet._fling_tick()
        assert (pet.x(), pet.y()) != start
        positions = []
        for _ in range(config.FLING_MAX_DURATION_MS // config.FLING_TICK_MS + 2):
            if not pet.fling_active:
                break
            pet._fling_tick()
            positions.append((pet.x(), pet.y()))
            assert cat_inside_screen(pet)
        assert not pet.fling_active and not pet.fling_timer.isActive()
        assert pet._fling_body is None
        assert len(positions) * config.FLING_TICK_MS < config.FLING_MAX_DURATION_MS
        assert cat_inside_screen(pet)
        # 有重力：最终落在底部
        assert pet.y() + pet.height() == pet._current_screen_rect().bottom() + 1

    def test_time_limit_forces_a_stop(self, pet, monkeypatch):
        monkeypatch.setattr(config, "FLING_FRICTION", 0.0)
        monkeypatch.setattr(config, "FLING_GROUND_FRICTION", 0.0)
        monkeypatch.setattr(config, "FLING_RESTITUTION_X", 1.0)
        monkeypatch.setattr(config, "FLING_GRAVITY", 0)
        pet._start_fling(1500, 0)         # 永动：只能靠时限收尾
        run_until_stopped(pet)
        assert cat_inside_screen(pet)

    def test_time_limit_mid_air_lands_on_the_floor(self, pet, monkeypatch):
        """超时时若还在空中（超高屏幕的最后几下微弹），直接落到底边，不能悬在半空。"""
        monkeypatch.setattr(config, "FLING_FRICTION", 0.0)
        monkeypatch.setattr(config, "FLING_RESTITUTION_Y", 1.0)   # 完全弹性：永远弹不完
        b = pet._fling_bounds_now()
        pet.move(round((b.x_min + b.x_max) / 2), round(b.y_max))
        pet._start_fling(0, -1500)
        run_until_stopped(pet)
        assert pet.y() + pet.height() == pet._current_screen_rect().bottom() + 1

    def test_corner_hit_squashes_against_the_harder_wall(self, pet):
        b = pet._fling_bounds_now()
        pet.move(round(b.x_max) - 5, round(b.y_max) - 3)   # 一帧内同时撞到右墙与底边
        pet._start_fling(1500, 300)
        pet._fling_tick()
        assert pet.x() == round(b.x_max) and pet.y() == round(b.y_max), "both walls hit"
        assert pet.anim_kind == "impact" and pet.anim_side == fling.RIGHT
        pet._stop_fling()

    def test_stop_restarts_idle_and_walk_timers(self, pet):
        pet.bubble.hide()
        pet.act_walk.setChecked(True)
        pet._start_fling(1500, 0)
        pet.idle_timer.stop()
        pet.walk_pause_timer.stop()
        pet.walk_target = QPoint(1, 1)
        run_until_stopped(pet)
        assert pet.idle_timer.isActive()
        assert pet.walk_target is None and pet._walk_pos is None
        assert pet.walk_pause_timer.isActive()

    def test_walking_is_paused_mid_flight(self, pet):
        pet.bubble.hide()
        pet.act_walk.setChecked(True)
        pet._start_fling(1500, 0)
        assert pet._walk_paused()
        region = pet._walk_region()
        pet.walk_target = QPoint(region.center().x(), region.bottom())
        before = (pet.x(), pet.y())
        pet._walk_tick()
        assert (pet.x(), pet.y()) == before
        pet.walk_target = None
        pet._on_walk_pause_done()
        assert pet.walk_target is None, "no new target while flying"

    def test_idle_chatter_stays_quiet_mid_flight(self, pet):
        pet.bubble.hide()
        pet._start_fling(1500, 0)
        pet._idle_chatter()
        assert not pet.bubble.isVisible() and pet.idle_timer.isActive()

    def test_facing_follows_horizontal_velocity(self, pet):
        pet._start_fling(-800, 0)
        assert pet.facing == -1
        pet._start_fling(800, 0)
        assert pet.facing == 1
        pet._start_fling(-800, 0)
        pet._start_fling(0, -800)           # 纯垂直：保持朝向
        assert pet.facing == -1
        pet._start_fling(config.FLING_TURN_MIN_SPEED * 0.5, 0)
        assert pet.facing == -1, "too slow to turn"
        pet._stop_fling()

    def test_wall_hit_plays_a_directional_impact_animation(self, pet):
        b = pet._fling_bounds_now()
        pet.move(round(b.x_max) - 5, round((b.y_min + b.y_max) / 2))
        pet._start_fling(1500, 0)
        pet._fling_tick()
        assert pet.x() == round(b.x_max)
        assert pet.anim_kind == "impact" and pet.anim_side == fling.RIGHT
        assert pet.anim_amp == pytest.approx(config.ANIM_IMPACT_AMP[1], abs=0.02)
        assert pet.anim_timer.isActive()
        assert pet.facing == -1, "bounced back: now flying left"
        pet._stop_fling()

    def test_soft_contact_does_not_animate(self, pet, monkeypatch):
        b = pet._fling_bounds_now()
        pet.move(round(b.x_max) - 1, round((b.y_min + b.y_max) / 2))
        pet.anim_kind = None
        pet._start_fling(config.FLING_IMPACT_MIN_SPEED * 0.5, 0)
        pet._fling_tick()
        assert pet.anim_kind is None
        pet._stop_fling()

    def test_geometry_rebuild_mid_flight_keeps_the_cat_on_screen(self, pet):
        b = pet._fling_bounds_now()
        pet.move(round(b.x_max), round(b.y_max))
        pet._start_fling(600, 0)
        pet._set_scale(config.MAX_SCALE)     # 窗口变大：旧边界作废
        assert pet.fling_active
        assert cat_inside_screen(pet)
        assert pet._fling_bounds == pet._fling_bounds_now()
        run_until_stopped(pet)
        assert cat_inside_screen(pet)


# ---------- Mixin：交互抢断 ----------

class TestInterrupts:
    def test_press_catches_the_pet_and_drags_seamlessly(self, pet, clock):
        drag(pet, clock, 2000, 0)
        for _ in range(5):
            pet._fling_tick()
        caught = (pet.x(), pet.y())
        gx, gy = pet.x() + 30, pet.y() + 30
        mouse(pet, QEvent.Type.MouseButtonPress, gx, gy)
        assert not pet.fling_active and not pet.fling_timer.isActive()
        assert pet.dragging and (pet.x(), pet.y()) == caught
        clock[0] += 0.5
        mouse(pet, QEvent.Type.MouseMove, gx + 40, gy + 10)
        assert (pet.x(), pet.y()) == (caught[0] + 40, caught[1] + 10)
        clock[0] += 0.5
        mouse(pet, QEvent.Type.MouseButtonRelease, gx + 40, gy + 10)
        assert not pet.fling_active and not pet.dragging

    def test_right_button_press_also_catches(self, pet, clock):
        pet._start_fling(1500, 0)
        mouse(pet, QEvent.Type.MouseButtonPress, pet.x() + 5, pet.y() + 5, Qt.RightButton)
        assert not pet.fling_active and not pet.dragging

    def test_context_menu_stops_the_fling(self, pet, monkeypatch):
        monkeypatch.setattr(pet.menu, "exec", lambda *a, **k: None)
        pet._start_fling(1500, 0)
        pet.contextMenuEvent(QContextMenuEvent(
            QContextMenuEvent.Mouse, QPoint(5, 5), QPoint(pet.x() + 5, pet.y() + 5)))
        assert not pet.fling_active and not pet.fling_timer.isActive()

    def test_wheel_stops_the_fling(self, pet):
        pet._start_fling(1500, 0)
        pet.wheelEvent(QWheelEvent(
            QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
        assert not pet.fling_active

    def test_input_follow_catches_the_pet_where_it_is(self, pet, monkeypatch):
        context = input_follow.InputContext(
            QRect(300, 200, 2, 20), QRect(250, 180, 140, 45), None,
            pet._current_screen_rect())
        monkeypatch.setattr(input_follow, "query_input_context", lambda: context)
        pet._start_fling(1500, -500)
        for _ in range(5):
            pet._fling_tick()
        foot = (pet.x() + pet.width() // 2, pet.y() + pet.height())
        pet._input_on_key()
        assert not pet.fling_active and pet.input_follow_active
        pet._stop_input_follow()
        assert (pet.x() + pet.width() // 2, pet.y() + pet.height()) == foot

    def test_reduced_motion_turning_on_mid_flight_stops_in_place(self, pet, monkeypatch):
        pet._start_fling(1500, 0)
        pet._fling_tick()
        here = (pet.x(), pet.y())
        monkeypatch.setattr(winapi, "query_reduced_motion", lambda: True)
        pet._poll_reduced_motion()
        assert not pet.fling_active and (pet.x(), pet.y()) == here

    def test_wake_up_catches_the_pet_before_greeting(self, pet):
        pet.bubble.hide()
        pet._start_fling(1500, 0)
        pet.wake_up()
        assert not pet.fling_active and pet.bubble.isVisible()

    def test_stop_is_idempotent(self, pet):
        pet._stop_fling()
        pet._start_fling(1500, 0)
        pet._stop_fling()
        pet._stop_fling()
        assert not pet.fling_active and not pet.fling_timer.isActive()


# ---------- 撞击动画 ----------

class TestImpactAnimation:
    @pytest.fixture
    def frozen(self, pet):
        """撞击动画播放中，用于几何断言：_layout(pet.t0) 处呼吸相位为 0，无需另行冻结。"""
        pet.hover_pos = None
        pet.head_angle = 0.0
        yield pet
        pet.anim_timer.stop()

    def _rect_at(self, pet, side, t, facing=1):
        pet.facing = facing
        pet.play_impact(side, 1.0)
        pet.anim_t = t
        return pet._layout(pet.t0)

    def test_amplitude_interpolates_with_strength(self, pet):
        lo, hi = config.ANIM_IMPACT_AMP
        pet.play_impact(fling.LEFT, 0.0)
        assert pet.anim_amp == lo
        pet.play_impact(fling.LEFT, 1.0)
        assert pet.anim_amp == hi
        pet.play_impact(fling.LEFT, 7.0)
        assert pet.anim_amp == hi
        pet.anim_timer.stop()

    def test_does_not_advance_the_click_cycle(self, pet):
        pet.play_impact(fling.BOTTOM, 1.0)
        assert pet.anim_index == 0
        pet.anim_timer.stop()

    def test_skipped_under_reduced_motion(self, pet):
        pet.reduced_motion = True
        pet.play_impact(fling.BOTTOM, 1.0)
        assert pet.anim_kind is None and not pet.anim_timer.isActive()

    @pytest.mark.parametrize("side", [fling.LEFT, fling.RIGHT, fling.TOP, fling.BOTTOM])
    def test_compresses_along_the_impact_axis(self, frozen, side):
        pet = frozen
        r = self._rect_at(pet, side, 0.2)
        if side in (fling.LEFT, fling.RIGHT):
            assert r.width() < pet.pix.width() * 0.7 and r.height() > pet.pix.height()
        else:
            assert r.height() < pet.pix.height() * 0.7 and r.width() > pet.pix.width()

    def test_left_and_right_walls_pin_the_wall_side_edge(self, frozen):
        pet = frozen
        cat = pet._cat_rect()
        for t in (0.1, 0.2, 0.6):
            assert abs(self._rect_at(pet, fling.LEFT, t).x() - cat.left()) < 1e-6
            r = self._rect_at(pet, fling.RIGHT, t)
            assert abs(r.x() + r.width() - (cat.left() + cat.width())) < 1e-6

    def test_mirrored_frame_pins_the_visual_wall_side(self, frozen):
        """向左飞（镜像绘制）撞左墙：画布坐标反向，视觉上仍是左缘钉住。"""
        pet = frozen
        cat = pet._cat_rect()
        r = self._rect_at(pet, fling.LEFT, 0.2, facing=-1)
        visual_left = pet.width() - (r.x() + r.width())
        assert abs(visual_left - cat.left()) < 1e-6

    def test_ceiling_pins_the_head_and_floor_pins_the_feet(self, frozen):
        pet = frozen
        cat = pet._cat_rect()
        foot = pet.height() - pet.bottom_pad - 3
        for t in (0.1, 0.2):
            assert abs(self._rect_at(pet, fling.TOP, t).y() - cat.top()) < 1e-6
        for t in (0.1, 0.2, 0.6):
            r = self._rect_at(pet, fling.BOTTOM, t)
            assert abs(r.y() + r.height() - foot) < 1e-6

    @pytest.mark.parametrize("side", [fling.LEFT, fling.RIGHT, fling.TOP, fling.BOTTOM])
    @pytest.mark.parametrize("facing", [1, -1])
    def test_stays_inside_the_window_padding(self, frozen, side, facing):
        pet = frozen
        for i in range(0, 101, 2):
            r = self._rect_at(pet, side, i / 100, facing)
            assert -1e-6 <= r.x() and r.x() + r.width() <= pet.width() + 1e-6
            assert -1e-6 <= r.y() and r.y() + r.height() <= pet.height() + 1e-6

    def test_finishes_and_resets(self, pet):
        pet.play_impact(fling.RIGHT, 1.0)
        for _ in range(200):
            pet._anim_tick()
            if pet.anim_kind is None:
                break
        assert pet.anim_kind is None and not pet.anim_timer.isActive()
        assert pet._anim_offsets() == (0.0, 0.0, 1.0, 1.0)
