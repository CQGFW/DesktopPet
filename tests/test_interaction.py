# -*- coding: utf-8 -*-
"""缩放锚点、滚轮语义、闲置提醒与语录挑选。"""
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from desktoppet import config


def wheel(pet, ax, ay):
    pet.wheelEvent(QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(ax, ay),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))


class TestZoom:
    def test_scaling_keeps_the_foot_anchored(self, pet):
        for target in (config.MIN_SCALE, config.MAX_SCALE):
            before = (pet.x() + pet.width() // 2, pet.y() + pet.height())
            pet._set_scale(target)
            after = (pet.x() + pet.width() // 2, pet.y() + pet.height())
            assert abs(before[0] - after[0]) <= 1 and before[1] == after[1]

    def test_vertical_wheel_zooms(self, pet):
        start = pet.scale
        wheel(pet, 0, 120)
        assert pet.scale > start
        wheel(pet, 0, -120)
        assert abs(pet.scale - start) < 1e-9

    def test_horizontal_only_wheel_is_ignored(self, pet):
        """触控板 / 倾斜滚轮的纯横向滚动不该改变大小。"""
        start = pet.scale
        wheel(pet, 120, 0)
        assert pet.scale == start
        wheel(pet, -120, 0)
        assert pet.scale == start


class TestIdleChatter:
    def test_timer_runs_from_startup_within_configured_range(self, pet):
        assert pet.idle_timer.isActive() and pet.idle_timer.isSingleShot()
        assert config.IDLE_MIN_MS <= pet.idle_timer.interval() <= config.IDLE_MAX_MS

    def test_pops_a_quote_and_reschedules(self, pet):
        pet.bubble.hide()
        pet._idle_chatter()
        assert pet.bubble.isVisible() and pet.bubble.text in config.QUOTES
        assert pet.idle_timer.isActive()

    def test_stays_quiet_while_dragging_but_keeps_rescheduling(self, pet):
        pet.bubble.hide()
        pet.dragging = True
        pet._idle_chatter()
        assert not pet.bubble.isVisible()
        assert pet.idle_timer.isActive()

    def test_interaction_restarts_the_timer(self, pet):
        pet.idle_timer.stop()
        wheel(pet, 0, 120)
        assert pet.idle_timer.isActive()


def test_quotes_never_repeat_back_to_back(pet):
    previous = pet._pick_quote()
    for _ in range(40):
        quote = pet._pick_quote()
        assert quote in config.QUOTES and quote != previous
        previous = quote
