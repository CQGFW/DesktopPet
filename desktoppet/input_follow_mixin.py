# -*- coding: utf-8 -*-
"""输入跟随 Mixin：前台输入时临时缩小并跟随光标，避开输入框与 IME 候选区。

停止输入 1 秒后恢复原位置与缩放。服从系统"减少动态效果"开关。"""
from PySide6.QtCore import QTimer, QPoint

from . import config, ime, input_follow, placement


class InputFollowMixin:
    """输入跟随的状态机：进入 → 轮询刷新位置 → 空闲超时退出并还原。

    依赖宿主提供：self.scale、self.input_follow_enabled、self.input_follow_scale、
    self.reduced_motion、self._set_scale()、self._apply_geometry()、
    self._stop_fling()、self.update()、self.size()、self.move()、self.x()、
    self.y()、self.width()、self.height()。"""

    def _init_input_follow(self):
        # 输入跟随：保存进入前的缩放 / 脚底位置，短周期刷新跨进程光标。
        self.input_follow_active = False
        self.input_saved_scale = None
        self.input_saved_foot = None
        self.input_idle_timer = QTimer(self)
        self.input_idle_timer.setSingleShot(True)
        self.input_idle_timer.timeout.connect(self._stop_input_follow)
        self.input_poll_timer = QTimer(self)
        self.input_poll_timer.setInterval(config.INPUT_POLL_MS)
        self.input_poll_timer.timeout.connect(self._input_follow_tick)

    def _move_to_input_context(self, context):
        pos = placement.safe_position(context.caret, context.focus,
                                      context.candidate, self.size(),
                                      context.screen)
        self.move(pos)

    def _set_input_follow(self, on):
        """开关输入跟随；关闭时立刻退出跟随并还原位置与缩放。"""
        self.input_follow_enabled = on
        if not on:
            self._stop_input_follow()
        self._schedule_save()

    def _set_input_follow_scale(self, value):
        """选择跟随大小档位。

        不重新缩放当前跟随：contextMenuEvent 弹菜单前必定先 _stop_input_follow()，
        用户不可能在跟随进行中改档位，下次输入时自然生效。"""
        self.input_follow_scale = value
        for choice, action in self.follow_scale_actions.items():
            action.setChecked(choice == value)
        self._schedule_save()

    def _input_follow_allowed(self):
        """输入跟随会让宠物在屏幕上大幅跳动，是最显眼的一种动效，
        因此与呼吸 / 转头 / 走动一样服从系统"减少动态效果"。"""
        return self.input_follow_enabled and not self.reduced_motion

    def _input_on_key(self):
        """Enter or refresh input-follow mode when the foreground exposes a caret."""
        if not self._input_follow_allowed():
            return
        if self.input_follow_active:
            # 已在跟随中：位置由 input_poll_timer 按 config.INPUT_POLL_MS 刷新，
            # 这里只需为按键续期空闲计时。跨进程查询很贵，不必每键重跑一次。
            self.input_idle_timer.start(config.INPUT_IDLE_MS)
            return
        context = input_follow.query_input_context()
        if context is None:
            return
        self._stop_fling()   # 飞行中被输入接住：先停在当前位置，再记锚点
        self.input_saved_scale = self.scale
        self.input_saved_foot = QPoint(
            self.x() + self.width() // 2, self.y() + self.height())
        self.input_follow_active = True
        self._set_scale(self.input_follow_scale)
        self.input_poll_timer.start()
        self._move_to_input_context(context)
        self.input_idle_timer.start(config.INPUT_IDLE_MS)

    def _input_follow_tick(self):
        """Refresh after the target application has processed the latest key."""
        if not self.input_follow_active:
            return
        context = input_follow.query_input_context()
        if context is not None:
            self._move_to_input_context(context)

    def _stop_input_follow(self):
        """Leave input mode and restore the exact pre-input scale and foot anchor."""
        self.input_idle_timer.stop()
        self.input_poll_timer.stop()
        ime.reset_cache()   # 下次进入输入跟随时重新探测，不沿用旧结论
        if not self.input_follow_active:
            return
        saved_scale = self.input_saved_scale
        saved_foot = QPoint(self.input_saved_foot)
        self.input_follow_active = False
        self.input_saved_scale = None
        self.input_saved_foot = None
        self._set_scale(saved_scale)
        self._apply_geometry(saved_foot.x(), saved_foot.y())
        self.update()
