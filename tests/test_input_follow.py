# -*- coding: utf-8 -*-
"""输入跟随的状态机：进入 / 幂等 / 各退出路径必须精确还原缩放与脚底锚点。"""
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QFocusEvent, QMouseEvent, QWheelEvent

from desktoppet import config, input_follow

CONTEXT = input_follow.InputContext(
    QRect(300, 200, 2, 20), QRect(250, 180, 140, 45), None, QRect(0, 0, 1280, 720))


@pytest.fixture
def caret(pet, monkeypatch):
    """让 query_input_context 返回一个固定的输入上下文，并记录初始锚点。"""
    monkeypatch.setattr(input_follow, "query_input_context", lambda: CONTEXT)
    return {"scale": pet.scale,
            "foot": (pet.x() + pet.width() // 2, pet.y() + pet.height())}


def assert_following(pet, caret):
    assert pet.input_follow_active
    # 跟随大小是绝对档位，与进入前的平时大小无关
    assert abs(pet.scale - pet.input_follow_scale) < 1e-9


def assert_restored(pet, caret):
    assert not pet.input_follow_active
    assert abs(pet.scale - caret["scale"]) < 1e-9
    assert (pet.x() + pet.width() // 2, pet.y() + pet.height()) == caret["foot"]


def press(pet, dx=5):
    pet.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(dx, dx),
        QPointF(pet.x() + dx, pet.y() + dx), Qt.LeftButton, Qt.LeftButton,
        Qt.NoModifier))


def release(pet, dx=5):
    pet.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(dx, dx),
        QPointF(pet.x() + dx, pet.y() + dx), Qt.LeftButton, Qt.NoButton,
        Qt.NoModifier))


def test_idle_timeout_is_one_second():
    assert config.INPUT_IDLE_MS == 1000


def test_key_activates_and_shrinks(pet, caret):
    pet._input_on_key()
    assert_following(pet, caret)
    assert pet.input_poll_timer.isActive() and pet.input_idle_timer.isActive()


def test_repeated_keys_are_idempotent(pet, caret):
    """连续敲键不能把已缩小的比例再当成"原始比例"存一次。"""
    pet._input_on_key()
    active_scale = pet.scale
    pet._input_on_key()
    assert pet.input_saved_scale == caret["scale"]
    assert pet.scale == active_scale


def test_repeated_keys_do_not_requery(pet, caret, monkeypatch):
    """跟随激活后位置由轮询定时器刷新，按键不该再触发昂贵的跨进程查询。"""
    pet._input_on_key()
    calls = []
    monkeypatch.setattr(input_follow, "query_input_context",
                        lambda: (calls.append(1), CONTEXT)[1])
    for _ in range(8):
        pet._input_on_key()
    assert calls == []
    assert pet.input_idle_timer.isActive()


def test_keyboard_toggle_does_not_block_input_follow(pet, caret):
    """键盘互动与输入跟随是彼此独立的功能。"""
    pet.act_kb.setChecked(False)
    pet._input_on_key()
    assert_following(pet, caret)


def test_reduced_motion_suppresses_input_follow(pet, caret):
    """跟随会让宠物在屏幕上大幅跳动，属于最显眼的动效，应服从系统设置。"""
    pet.reduced_motion = True
    pet._input_on_key()
    assert not pet.input_follow_active


def test_reduced_motion_turning_on_mid_follow_restores(pet, caret, monkeypatch):
    from desktoppet import winapi
    pet._input_on_key()
    assert_following(pet, caret)
    monkeypatch.setattr(winapi, "query_reduced_motion", lambda: True)
    pet._poll_reduced_motion()
    assert_restored(pet, caret)


def test_menu_toggle_suppresses_input_follow(pet, caret):
    pet.act_input.setChecked(False)
    pet._input_on_key()
    assert not pet.input_follow_active


def test_disabling_toggle_mid_follow_restores(pet, caret):
    pet._input_on_key()
    assert_following(pet, caret)
    pet.act_input.setChecked(False)
    assert_restored(pet, caret)


def test_missing_caret_never_activates(pet, caret, monkeypatch):
    monkeypatch.setattr(input_follow, "query_input_context", lambda: None)
    pet._input_on_key()
    assert_restored(pet, caret)


@pytest.mark.parametrize("exit_path", ["stop", "click", "press", "wheel", "focus_out"])
def test_every_exit_path_restores_scale_and_foot(pet, caret, exit_path):
    """每个用户交互退出路径都必须还原缩放和脚底锚点。"""
    pet._input_on_key()
    assert_following(pet, caret)

    if exit_path == "stop":
        pet._stop_input_follow()
    elif exit_path == "click":
        press(pet)
        release(pet)
    elif exit_path == "press":
        press(pet)
    elif exit_path == "wheel":
        pet.wheelEvent(QWheelEvent(
            QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 0),
            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
    elif exit_path == "focus_out":
        pet.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))

    assert_restored(pet, caret)


class TestFollowScale:
    """跟随大小是可选的绝对档位，而不是相对平时大小的倍率。"""

    def test_default_choice_is_one_of_the_choices(self):
        assert config.INPUT_SCALE_DEFAULT in config.INPUT_SCALE_CHOICES

    def test_defaults_to_the_configured_choice(self, pet):
        assert pet.input_follow_scale == config.INPUT_SCALE_DEFAULT

    @pytest.mark.parametrize("choice", config.INPUT_SCALE_CHOICES)
    def test_follow_scale_equals_the_selected_choice(self, pet, caret, choice):
        pet._set_input_follow_scale(choice)
        pet._input_on_key()
        assert pet.input_follow_active
        assert abs(pet.scale - choice) < 1e-9

    @pytest.mark.parametrize("normal", [config.MIN_SCALE, 1.0, config.MAX_SCALE])
    def test_follow_scale_is_absolute_not_relative(self, pet, caret, normal):
        """平时大小无论调到多大多小，跟随时都是所选档位那么大。

        改动前是 平时大小 x 0.2，平时调到 25% 时跟随只剩 5%（约 13px），几乎不可见。"""
        pet._set_scale(normal)
        pet._set_input_follow_scale(0.30)
        pet._input_on_key()
        assert abs(pet.scale - 0.30) < 1e-9

    def test_exit_still_restores_the_normal_scale(self, pet, caret):
        """换档位不能影响还原目标——还原的始终是进入前的平时大小。"""
        pet._set_scale(0.75)
        foot = (pet.x() + pet.width() // 2, pet.y() + pet.height())
        pet._set_input_follow_scale(0.40)
        pet._input_on_key()
        assert abs(pet.scale - 0.40) < 1e-9
        pet._stop_input_follow()
        assert abs(pet.scale - 0.75) < 1e-9
        assert (pet.x() + pet.width() // 2, pet.y() + pet.height()) == foot
