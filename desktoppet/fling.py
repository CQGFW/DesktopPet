# -*- coding: utf-8 -*-
"""惯性抛掷的物理核心：释放速度采样与屏幕内回弹积分。

纯数学，不依赖 Qt 与宠物状态，可独立单测。坐标系与屏幕一致：x 向右、y 向下；
长度单位为像素，时间单位为秒。"""
import math
from collections import deque
from dataclasses import dataclass

LEFT, RIGHT, TOP, BOTTOM = "left", "right", "top", "bottom"


class VelocityTracker:
    """拖拽轨迹采样器：保留最近的 (t, x, y) 样本，松手时估算瞬时速度。

    速度取采样窗口内最早的样本到松手点的平均速度。松手前停顿超过 hold 视为「放下」，
    速度归零；停顿不足 hold 时，因为分母包含停顿时长，速度会随之自然衰减。"""

    def __init__(self, window, hold, min_span=0.02, maxlen=256):
        self.window = float(window)      # 采样窗口时长（秒）
        self.hold = float(hold)          # 松手前允许的最长停顿（秒）
        self.min_span = float(min_span)  # 时间跨度不足此值的样本视为噪声
        self._samples = deque(maxlen=maxlen)

    def __len__(self):
        return len(self._samples)

    def reset(self):
        self._samples.clear()

    def add(self, t, x, y):
        """记录一个样本；比 窗口 + 停顿阈值 还老的样本不可能再被用到，顺手丢弃。"""
        self._samples.append((float(t), float(x), float(y)))
        cutoff = t - self.window - self.hold
        while len(self._samples) > 1 and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def velocity(self, now, x, y):
        """在 now 时刻于 (x, y) 松手，返回 (vx, vy)（像素/秒）。"""
        if not self._samples:
            return 0.0, 0.0
        if now - self._samples[-1][0] > self.hold:
            return 0.0, 0.0
        cutoff = now - self.window
        first = next((s for s in self._samples if s[0] >= cutoff), self._samples[-1])
        span = now - first[0]
        if span < self.min_span:
            return 0.0, 0.0
        return (x - first[1]) / span, (y - first[2]) / span


def limit_speed(vx, vy, max_speed):
    """速度模长超过上限时按比例缩短，方向不变。"""
    speed = math.hypot(vx, vy)
    if speed <= max_speed or speed == 0.0:
        return vx, vy
    k = max_speed / speed
    return vx * k, vy * k


@dataclass(frozen=True)
class Body:
    """飞行中的宠物：窗口左上角的浮点位置与速度。"""
    x: float
    y: float
    vx: float
    vy: float

    @property
    def speed(self):
        return math.hypot(self.vx, self.vy)


@dataclass(frozen=True)
class Bounds:
    """窗口左上角允许的取值范围；某轴 lo > hi（区域比窗口还小）时退化为中点。"""
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    @classmethod
    def normalized(cls, x_min, x_max, y_min, y_max):
        if x_min > x_max:
            x_min = x_max = (x_min + x_max) / 2.0
        if y_min > y_max:
            y_min = y_max = (y_min + y_max) / 2.0
        return cls(float(x_min), float(x_max), float(y_min), float(y_max))

    def clamp(self, x, y):
        return (max(self.x_min, min(x, self.x_max)),
                max(self.y_min, min(y, self.y_max)))


@dataclass(frozen=True)
class Params:
    friction: float          # 空气阻尼系数（1/秒）
    ground_friction: float   # 贴地滑行的额外阻尼（1/秒）
    gravity: float           # 向下加速度（像素/秒²）
    restitution_x: float     # 撞左右墙的弹性恢复系数
    restitution_y: float     # 撞顶 / 底的弹性恢复系数
    bounce_min_speed: float  # 撞底速度低于此值不再弹起，直接贴地
    stop_speed: float        # 贴地且速度低于此值即停止


def _bounce(pos, vel, lo, hi, restitution, wall_lo, wall_hi):
    """单轴碰撞：越界则夹回边界并反向衰减。返回 (pos, vel, hit)，hit 为 (墙, 撞击速度) 或 None。"""
    if lo >= hi:                  # 退化轴：钉在中点，不动
        return lo, 0.0, None
    if pos <= lo:
        if vel < 0:
            return lo, -vel * restitution, (wall_lo, -vel)
        return lo, vel, None
    if pos >= hi:
        if vel > 0:
            return hi, -vel * restitution, (wall_hi, vel)
        return hi, vel, None
    return pos, vel, None


def step(body, bounds, dt, params):
    """前进 dt 秒：重力 → 阻尼 → 位移 → 撞墙夹紧并反弹 → 贴地滑行阻尼。

    返回 (新状态, 碰撞列表)；碰撞项为 (墙, 撞击速度)，同一帧撞角落时会有两项。"""
    damp = math.exp(-params.friction * dt)
    vx = body.vx * damp
    vy = (body.vy + params.gravity * dt) * damp
    x = body.x + vx * dt
    y = body.y + vy * dt

    x, vx, hit_x = _bounce(x, vx, bounds.x_min, bounds.x_max,
                           params.restitution_x, LEFT, RIGHT)
    y, vy, hit_y = _bounce(y, vy, bounds.y_min, bounds.y_max,
                           params.restitution_y, TOP, BOTTOM)
    if hit_y is not None and hit_y[0] == BOTTOM and hit_y[1] < params.bounce_min_speed:
        vy, hit_y = 0.0, None     # 弹跳高度已可忽略：贴地，不再无限微弹
    if y >= bounds.y_max and vy == 0.0:
        vx *= math.exp(-params.ground_friction * dt)

    hits = [hit for hit in (hit_x, hit_y) if hit is not None]
    return Body(x, y, vx, vy), hits


def settled(body, bounds, params):
    """停止判定：速度低于停止阈值，且（有重力时）已贴地——空中的慢速只是抛物线顶点。"""
    if body.speed >= params.stop_speed:
        return False
    return params.gravity <= 0 or body.y >= bounds.y_max
