# -*- coding: utf-8 -*-
"""用 QSettings 持久化右键菜单的开关与缩放比例。

存储位置交给 Qt 按平台决定（Windows 上是注册表 HKCU\\Software\\DesktopPet）。
读取一律带默认值并做范围校验：配置可能来自旧版本、也可能被手工改坏，
不能让它把程序带进非法状态（例如 0 倍缩放）。"""
from PySide6.QtCore import QSettings

from . import config, debuglog

ORGANIZATION = "DesktopPet"
APPLICATION = "DesktopPet"

# 键名 -> 默认值；与右键菜单里的开关一一对应
DEFAULTS = {
    "topmost": True,
    "walk": False,
    "keyboard": True,
    "input_follow": True,
}
DEFAULT_SCALE = 1.0


def _store():
    return QSettings(ORGANIZATION, APPLICATION)


def load():
    """读取已保存的偏好，返回 (开关字典, 缩放比例)。读失败时退回默认值。"""
    flags = dict(DEFAULTS)
    scale = DEFAULT_SCALE
    try:
        store = _store()
        for key, default in DEFAULTS.items():
            flags[key] = store.value(key, default, type=bool)
        scale = store.value("scale", DEFAULT_SCALE, type=float)
    except Exception:
        debuglog.exception("settings.load")
        return dict(DEFAULTS), DEFAULT_SCALE
    if not (config.MIN_SCALE <= scale <= config.MAX_SCALE):
        scale = DEFAULT_SCALE      # 越界 / 损坏的值一律按默认处理
    return flags, scale


def save(flags, scale):
    """写回偏好。失败只记日志：存不下设置不该影响宠物本身的运行。"""
    try:
        store = _store()
        for key in DEFAULTS:
            store.setValue(key, bool(flags[key]))
        store.setValue("scale", float(scale))
        store.sync()
    except Exception:
        debuglog.exception("settings.save")
