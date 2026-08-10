# -*- coding: utf-8 -*-
"""偏好持久化：往返、默认值、损坏值兜底，以及 Pet 的读写接线。"""
from desktoppet import config, settings


class TestRoundTrip:
    def test_saved_flags_and_scale_come_back(self, qapp):
        settings.save({"topmost": False, "walk": True,
                       "keyboard": False, "input_follow": False}, 0.75)
        flags, scale = settings.load()
        assert flags == {"topmost": False, "walk": True,
                         "keyboard": False, "input_follow": False}
        assert abs(scale - 0.75) < 1e-9

    def test_booleans_survive_as_booleans(self, qapp):
        """QSettings 在 INI / 注册表里存的是字符串，读回来必须仍是 bool，
        否则 "false" 这种真值字符串会把开关默默打开。"""
        settings.save(dict(settings.DEFAULTS, topmost=False), 1.0)
        flags, _ = settings.load()
        assert flags["topmost"] is False


class TestDefaults:
    def test_missing_keys_fall_back(self, qapp, monkeypatch):
        monkeypatch.setattr(settings, "APPLICATION", "DesktopPet-Unwritten")
        flags, scale = settings.load()
        assert flags == settings.DEFAULTS
        assert scale == settings.DEFAULT_SCALE

    def test_out_of_range_scale_is_rejected(self, qapp):
        for bogus in (0.0, -1.0, 99.0):
            settings.save(dict(settings.DEFAULTS), bogus)
            _, scale = settings.load()
            assert config.MIN_SCALE <= scale <= config.MAX_SCALE
            assert scale == settings.DEFAULT_SCALE


class TestPetWiring:
    def test_non_persisting_pet_never_writes(self, pet, monkeypatch):
        """测试与临时实例不该污染用户已保存的偏好。"""
        written = []
        monkeypatch.setattr(settings, "save",
                            lambda *a: written.append(a))
        pet.act_walk.setChecked(True)
        pet.save_settings()
        assert written == []

    def test_current_flags_track_the_menu(self, pet):
        pet.act_topmost.setChecked(False)
        pet.act_walk.setChecked(True)
        pet.act_kb.setChecked(False)
        pet.act_input.setChecked(False)
        assert pet._current_flags() == {"topmost": False, "walk": True,
                                        "keyboard": False, "input_follow": False}

    def test_persisted_scale_ignores_the_input_follow_shrink(self, pet, monkeypatch):
        """输入跟随期间 self.scale 是临时缩小值，存进去会越存越小。"""
        from desktoppet import input_follow
        from PySide6.QtCore import QRect
        monkeypatch.setattr(input_follow, "query_input_context",
                            lambda: input_follow.InputContext(
                                QRect(300, 200, 2, 20), None, None,
                                QRect(0, 0, 1280, 720)))
        pet._set_scale(0.8)
        pet._input_on_key()
        assert pet.input_follow_active and pet.scale < 0.8
        assert abs(pet._persistable_scale() - 0.8) < 1e-9
