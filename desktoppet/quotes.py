# -*- coding: utf-8 -*-
r"""语录：按情境分池，内置文件随程序分发，用户文件可覆盖。

内置 quotes.json 放在项目根（打包时进 datas）；用户文件位于
%APPDATA%\DesktopPet\quotes.json，存在时其中出现的池整体覆盖内置同名池。
用户文件按修改时间惰性重载：编辑保存后下一条语录即生效，不必重启。"""
import json
import os
import random
import shutil
import time

from . import config, debuglog

CONTEXTS = ("click", "idle")
TIME_POOLS = ("morning", "noon", "afternoon", "evening", "night")
USER_FILE = "quotes.json"

_builtin = None
_user_cache = None        # (mtime, pools)；mtime None 表示文件不存在


def builtin_path():
    return config.resource_path("quotes.json")


def user_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "DesktopPet", USER_FILE)


def _load(path):
    """读一份语录文件；只保留值为非空字符串列表的池，其余键（如说明）忽略。"""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    pools = {}
    for key, value in data.items():
        if key.startswith("_") or not isinstance(value, list):
            continue
        items = [str(x).strip() for x in value if str(x).strip()]
        if items:
            pools[key] = items
    return pools


def _builtin_pools():
    global _builtin
    if _builtin is None:
        try:
            _builtin = _load(builtin_path())
        except (OSError, ValueError):
            debuglog.exception("quotes.builtin")
            _builtin = {"click": ["喵~"], "idle": ["喵~"]}
    return _builtin


def _user_pools():
    """用户文件的池；文件缺失 / 损坏时返回空 dict（继续使用内置）。"""
    global _user_cache
    path = user_path()
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        mtime = None
    if _user_cache is not None and _user_cache[0] == mtime:
        return _user_cache[1]
    pools = {}
    if mtime is not None:
        try:
            pools = _load(path)
        except (OSError, ValueError):
            debuglog.exception("quotes.user")
    _user_cache = (mtime, pools)
    return pools


def pools():
    merged = dict(_builtin_pools())
    merged.update(_user_pools())
    return merged


def reset_cache():
    global _builtin, _user_cache
    _builtin = None
    _user_cache = None


def time_pool(hour):
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 14:
        return "noon"
    if 14 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "night"


def candidates(context, hour=None):
    """某情境在当前时段的候选语录：情境池 + 时段池；情境池缺失时退回所有情境池。"""
    all_pools = pools()
    if hour is None:
        hour = time.localtime().tm_hour
    items = list(all_pools.get(context, []))
    if not items:
        for key in CONTEXTS:
            items.extend(all_pools.get(key, []))
    items.extend(all_pools.get(time_pool(hour), []))
    return items or ["喵~"]


def pick(context, last=None, hour=None):
    """随机选一条，避免与上一条重复。"""
    items = candidates(context, hour)
    return random.choice([x for x in items if x != last] or items)


def all_quotes():
    return [q for items in pools().values() for q in items]


def ensure_user_file():
    """用户文件不存在时从内置复制一份；返回路径，失败返回 None。"""
    path = user_path()
    if os.path.exists(path):
        return path
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(builtin_path(), path)
        return path
    except OSError:
        debuglog.exception("quotes.ensure_user_file")
        return None
