# -*- coding: utf-8 -*-
"""自动走动 Mixin：在当前屏幕右下 1/4 区域内随机游走。

到达目标后停留数秒再走向下一处；拖拽 / 右键菜单 / 气泡 / 减少动态效果时暂停。"""
import math
import random

from PySide6.QtCore import QTimer, QPoint, QRect

from . import config


class WalkMixin:
    """自动走动的状态机与帧步进。

    依赖宿主提供：self.dragging、self.reduced_motion、self.input_follow_active、
    self.menu、self.bubble、self._current_screen_rect()、self.width()、
    self.height()、self.move()、self.x()、self.y()、self._schedule_save()。"""

    def _init_walk(self):
        # 自动走动状态：目标点为脚底中心的屏幕坐标，None 表示正在停留；
        # _walk_pos 为浮点脚底位置（避免逐帧取整累计出速度/方向量化误差）
        self.walk_enabled = False
        self.walk_target = None
        self._walk_pos = None
        self.walk_timer = QTimer(self)
        self.walk_timer.setInterval(config.WALK_TICK_MS)
        self.walk_timer.timeout.connect(self._walk_tick)
        self.walk_pause_timer = QTimer(self)
        self.walk_pause_timer.setSingleShot(True)
        self.walk_pause_timer.timeout.connect(self._on_walk_pause_done)

    def _walk_region(self):
        """走动限定区域：宠物当前所在屏幕可用区域的右下 1/4。"""
        scr = self._current_screen_rect()
        return QRect(scr.center(), scr.bottomRight())

    def _foot_bounds(self):
        """脚底中心点在走动区域内的合法区间 (lo_x, hi_x, lo_y, hi_y)：
        向内收缩半个窗口宽 / 整个窗口高，保证窗口整体不越出区域。"""
        r = self._walk_region()
        lo_x, hi_x = r.left() + self.width() // 2, r.right() - self.width() // 2
        lo_y, hi_y = r.top() + self.height(), r.bottom()
        if lo_x > hi_x:     # 区域比窗口还窄 / 矮时退化为贴中线 / 贴底
            lo_x = hi_x = r.center().x()
        if lo_y > hi_y:
            lo_y = hi_y = r.bottom()
        return lo_x, hi_x, lo_y, hi_y

    def _clamp_foot(self, fx, fy):
        """把脚底中心点收进走动区域的合法区间。"""
        lo_x, hi_x, lo_y, hi_y = self._foot_bounds()
        return max(lo_x, min(fx, hi_x)), max(lo_y, min(fy, hi_y))

    def _walk_paused(self):
        """走动的临时暂停条件：拖拽 / 右键菜单打开 / 气泡显示中 / 减少动态效果 / 输入跟随。"""
        return (self.dragging or self.reduced_motion or self.input_follow_active
                or self.menu.isVisible() or self.bubble.isVisible())

    def _pick_walk_target(self):
        """在合法区间内均匀随机选下一个脚底目标点（不经 clamp，避免边缘聚集）。"""
        lo_x, hi_x, lo_y, hi_y = self._foot_bounds()
        self.walk_target = QPoint(random.randint(lo_x, hi_x),
                                  random.randint(lo_y, hi_y))
        self._walk_pos = None   # 下一 tick 从当前窗口位置重新起步

    def _on_walk_pause_done(self):
        """停留结束：若正处于暂停态则不选新目标（相当于冻结停留），
        恢复后由 _walk_tick 兜底重新计时。"""
        if self.walk_enabled and not self._walk_paused():
            self._pick_walk_target()

    def _set_walk(self, on):
        self.walk_enabled = on
        if on:
            self._pick_walk_target()
            self.walk_timer.start()
        else:
            self.walk_timer.stop()
            self.walk_pause_timer.stop()
            self.walk_target = None
            self._walk_pos = None
        self._schedule_save()

    def _restart_walk_pause(self):
        self.walk_pause_timer.start(
            random.randint(config.WALK_PAUSE_MIN_MS, config.WALK_PAUSE_MAX_MS))

    def _walk_tick(self):
        """每帧向目标匀速走一步；浮点累计位置，move 时才取整。"""
        if self._walk_paused():
            return
        if self.walk_target is None:
            # 停留计时被暂停冻结 / 外部打断后兜底重新排期
            if not self.walk_pause_timer.isActive():
                self._restart_walk_pause()
            return
        if self._walk_pos is None:
            self._walk_pos = (float(self.x() + self.width() // 2),
                              float(self.y() + self.height()))
        fx, fy = self._walk_pos
        dx = self.walk_target.x() - fx
        dy = self.walk_target.y() - fy
        dist = math.hypot(dx, dy)
        step = config.WALK_SPEED * config.WALK_TICK_MS / 1000.0
        if dist <= step:    # 到达：吸附到目标点并停留一会儿
            nx, ny = self.walk_target.x(), self.walk_target.y()
            self.walk_target = None
            self._walk_pos = None
            self._restart_walk_pause()
        else:
            fx += dx / dist * step
            fy += dy / dist * step
            self._walk_pos = (fx, fy)
            nx, ny = round(fx), round(fy)
        self.move(nx - self.width() // 2, ny - self.height())
