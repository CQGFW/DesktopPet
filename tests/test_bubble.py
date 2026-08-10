# -*- coding: utf-8 -*-
"""气泡：按当前屏幕定位、贴边翻转、收进屏幕、停留时长随文字长度。"""
from PySide6.QtCore import QRect

from desktoppet import config
from desktoppet.bubble import Bubble

SCREEN = QRect(0, 0, 1280, 720)


class TestPlacement:
    def test_say_refreshes_from_the_pets_current_screen(self, pet):
        """宠物可能在启动后被拖到别的显示器，不能用启动时缓存的屏幕。"""
        pet.screen_rect = QRect(-9999, -9999, 10, 10)
        pet.say("屏幕定位测试")
        assert pet.screen_rect == pet.screen().availableGeometry()

    def test_bubble_shows_with_a_running_timer(self, pet):
        pet.say("测试一条比较长的语录，看看自动换行和居中效果如何。")
        assert pet.bubble.isVisible() and pet.bubble.timer.isActive()

    def test_flips_below_when_near_the_top_of_the_screen(self, pet):
        pet.say("先说一句")           # 刷新 screen_rect
        pet.move(pet.x(), pet.screen_rect.top() - pet.top_pad)
        pet.say("顶部测试")
        assert not pet.bubble.tail_down

    def test_stays_inside_the_screen_vertically(self, qapp):
        """贴近上 / 下边缘时宁可尾巴对不准，也不要整条气泡跑出屏幕。"""
        bubble = Bubble()
        try:
            bubble.popup("靠下边缘", 640, SCREEN.bottom() + 200, False, SCREEN)
            assert bubble.geometry().bottom() <= SCREEN.bottom()
            bubble.popup("靠上边缘", 640, SCREEN.top() - 200, True, SCREEN)
            assert bubble.geometry().top() >= SCREEN.top()
        finally:
            bubble.hide()

    def test_stays_inside_the_screen_horizontally(self, qapp):
        bubble = Bubble()
        try:
            bubble.popup("靠右边缘", SCREEN.right() + 200, 400, True, SCREEN)
            assert bubble.geometry().right() <= SCREEN.right()
            bubble.popup("靠左边缘", SCREEN.left() - 200, 400, True, SCREEN)
            assert bubble.geometry().left() >= SCREEN.left()
        finally:
            bubble.hide()


class TestDuration:
    def test_short_text_keeps_the_two_second_floor(self):
        assert Bubble.duration_ms("喵") == config.BUBBLE_MIN_MS

    def test_longer_text_stays_on_screen_longer(self):
        short = Bubble.duration_ms("短句")
        long = Bubble.duration_ms("这是一条相当长的语录" * 2)
        assert long > short

    def test_never_exceeds_the_cap(self):
        assert Bubble.duration_ms("很长的语录" * 100) == config.BUBBLE_MAX_MS
