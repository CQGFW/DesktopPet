# -*- coding: utf-8 -*-
"""动画 Mixin：呼吸起伏、头部鼠标跟随、点击互动动画（跳跃/压扁/抖动）。

与系统"减少动态效果"开关联动：开启时所有动画静默，头部立即回正，
输入跟随一并退出并还原。"""
import math
import time

from PySide6.QtCore import QTimer

from . import config, winapi


class AnimationMixin:
    """呼吸 / 头部跟随 / 互动动画的状态与帧驱动。

    依赖宿主提供：self.pix（动画幅度计算）、self.update()、self.dragging、
    self.hover_pos、self.facing、self._cat_rect()、self._stop_input_follow()。"""

    def _init_animation(self):
        # 互动动画状态
        self.anim_kind = None
        self.anim_t = 0.0
        self.anim_index = 0
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(config.ANIM_TICK_MS)
        self.anim_timer.timeout.connect(self._anim_tick)

        # 呼吸 / 头部跟随状态
        self.reduced_motion = winapi.query_reduced_motion()
        self.t0 = time.monotonic()
        self.head_angle = 0.0     # 当前头部角度（度，正值向右倾）
        self.head_target = 0.0
        self.hover_pos = None     # 悬停时的窗口内坐标；None 表示不在窗口内

        # 动画帧驱动（呼吸 + 头部角度平滑）；减少动态效果时自动静默
        self.frame_timer = QTimer(self)
        self.frame_timer.timeout.connect(self._frame)
        self.frame_timer.start(config.FRAME_MS)

        # 定期复查系统"减少动态效果"开关，随系统设置即时降级 / 恢复
        self.rm_timer = QTimer(self)
        self.rm_timer.timeout.connect(self._poll_reduced_motion)
        self.rm_timer.start(4000)

    # ---------- 呼吸 / 头部跟随 ----------
    def _breath_scales(self, t):
        """呼吸缩放系数 (宽, 高)：纵向正弦起伏、横向轻微反相；减少动态效果时恒 1。"""
        if self.reduced_motion:
            return 1.0, 1.0
        ph = math.sin(2 * math.pi * (t - self.t0) / config.BREATH_PERIOD)
        return 1.0 - config.BREATH_AMP_X * ph, 1.0 + config.BREATH_AMP_Y * ph

    def _update_head_target(self):
        """按鼠标相对颈部转轴的方位更新头部目标角；不悬停 / 拖拽 / 降级时回正。"""
        if (self.reduced_motion or self.dragging or self.hover_pos is None
                or not self._cat_rect().contains(self.hover_pos)):
            self.head_target = 0.0
            return
        r = self._cat_rect()
        pivot_x = config.HEAD_PIVOT[0] if self.facing > 0 else 1 - config.HEAD_PIVOT[0]
        px = r.x() + r.width() * pivot_x        # 镜像时转轴也在镜像位置
        py = r.y() + r.height() * config.HEAD_PIVOT[1]
        dx = self.hover_pos.x() - px
        dy = self.hover_pos.y() - py
        ang = math.degrees(math.atan2(dx, max(8.0, -dy))) * config.HEAD_GAIN
        self.head_target = max(-config.HEAD_MAX_DEG, min(config.HEAD_MAX_DEG, ang))

    def _frame(self):
        """帧驱动：头部角度指数趋近目标 + 呼吸重绘；无动画需求时不重绘。"""
        self._update_head_target()
        if self.reduced_motion:
            # 减少动态效果：头部立即回正（不做平滑过渡），静止后不再重绘
            if self.head_angle == 0.0:
                return
            self.head_angle = 0.0
            self.update()
            return
        k = 1.0 - math.exp(-config.FRAME_MS / 1000.0 / config.HEAD_TAU)
        self.head_angle += (self.head_target - self.head_angle) * k
        if abs(self.head_angle - self.head_target) < 0.02:
            self.head_angle = self.head_target
        self.update()

    def _poll_reduced_motion(self):
        rm = winapi.query_reduced_motion()
        if rm != self.reduced_motion:
            self.reduced_motion = rm
            if rm:
                self.head_target = 0.0
                self.head_angle = 0.0
                self.anim_kind = None
                self.anim_timer.stop()
                self._stop_input_follow()   # 跟随属于动效，一并退出并还原
            else:
                self.t0 = time.monotonic()   # 呼吸从静止相位平滑起步
            self.update()

    # ---------- 互动动画 ----------
    def play_anim(self):
        """点击时轮流触发：跳跃 → 压扁回弹 → 左右抖动；减少动态效果时跳过。"""
        if self.reduced_motion:
            return
        self.anim_kind = config.ANIM_KINDS[self.anim_index % len(config.ANIM_KINDS)]
        self.anim_index += 1
        self.anim_t = 0.0
        self.anim_timer.start()

    def _anim_tick(self):
        self.anim_t += config.ANIM_TICK_MS / config.ANIM_DUR[self.anim_kind]
        if self.anim_t >= 1.0:
            self.anim_kind = None
            self.anim_timer.stop()
        self.update()

    def _anim_offsets(self):
        """当前动画帧的绘制参数：(水平偏移, 抬升高度, 宽度系数, 高度系数)。"""
        k, t = self.anim_kind, self.anim_t
        if k == "jump":
            # 抛物线：t=0.5 时到达最高点
            return 0.0, self.pix.height() * 0.30 * 4 * t * (1 - t), 1.0, 1.0
        if k == "squash":
            if t < 0.35:            # 压下去
                sy = 1 - 0.38 * math.sin(t / 0.35 * math.pi / 2)
            else:                   # 弹回来，带轻微过冲
                u = (t - 0.35) / 0.65
                sy = 1 - 0.38 * math.exp(-4 * u) * math.cos(u * 1.5 * math.pi)
            return 0.0, 0.0, 1 + (1 - sy) * 0.6, sy   # 压扁时变宽，近似保体积
        if k == "shake":
            # 衰减正弦：3 个来回，幅度递减
            amp = self.pix.width() * 0.055
            return amp * math.exp(-3 * t) * math.sin(t * 6 * math.pi), 0.0, 1.0, 1.0
        return 0.0, 0.0, 1.0, 1.0
