# -*- coding: utf-8 -*-
"""输入跟随探测的诊断记录。

输入跟随是最脆弱的模块：插入符可能来自 GUITHREADINFO 或 UIA，候选框探测又有
微信 / IMM / UIA 三条路径外加节流缓存。新输入法或新应用上出问题时，光看
"跟不跟"无从下手。这里记录每次探测走了哪条路径、耗时多少，并做两件事：

1. 累计统计 + 最近一次探测的摘要，右键菜单「复制输入跟随诊断」可一键复制；
2. 开启 DESKTOPPET_DEBUG 时，路径 / 前台进程发生变化才写一行日志（轮询
   50ms 一次，逐次记录会刷屏）。

记录本身只做字典赋值与 time.monotonic()，不引入新的跨进程调用。"""
import time
from collections import Counter

from . import debuglog

# 最近一次 query_input_context 的摘要字段
last = {}
# 累计统计
stats = Counter()
_durations = []           # 最近 N 次 query 总耗时（ms）
_MAX_SAMPLES = 200
_last_signature = None
_last_log_time = 0.0
LOG_HEARTBEAT_S = 5.0     # 路径不变时也每隔几秒记一行，证明轮询还活着


def reset():
    global _last_signature, _last_log_time
    last.clear()
    stats.clear()
    _durations.clear()
    _last_signature = None
    _last_log_time = 0.0


class Timer:
    """with 块计时（毫秒），供各探测路径记录耗时。"""
    def __enter__(self):
        self._t0 = time.monotonic()
        return self

    def __exit__(self, *_):
        self.ms = (time.monotonic() - self._t0) * 1000.0


def record_query(**fields):
    """query_input_context 收尾时调用：更新摘要、累计计数并按需写日志。"""
    global _last_signature, _last_log_time
    last.clear()
    last.update(fields)
    stats["queries"] += 1
    if fields.get("result") == "ok":
        stats["ok"] += 1
    stats["caret:%s" % fields.get("caret_source")] += 1
    stats["candidate:%s" % fields.get("candidate_source")] += 1
    ms = fields.get("total_ms")
    if ms is not None:
        _durations.append(ms)
        del _durations[:-_MAX_SAMPLES]
    if debuglog.enabled():
        signature = (fields.get("result"), fields.get("caret_source"),
                     fields.get("candidate_source"), fields.get("process"))
        now = time.monotonic()
        if signature != _last_signature or now - _last_log_time >= LOG_HEARTBEAT_S:
            _last_signature = signature
            _last_log_time = now
            debuglog.log("input_follow: " + summary_line(fields))


def summary_line(fields=None):
    f = last if fields is None else fields
    parts = ["result=%s" % f.get("result"),
             "process=%s" % f.get("process"),
             "caret=%s" % f.get("caret_source"),
             "candidate=%s" % f.get("candidate_source")]
    for key in ("gui_ms", "uia_caret_ms", "wechat_ms", "imm_ms", "uia_cand_ms", "total_ms"):
        if f.get(key) is not None:
            parts.append("%s=%.1f" % (key, f[key]))
    if f.get("caret") is not None:
        parts.append("caret_rect=%s" % (f["caret"],))
    if f.get("candidate") is not None:
        parts.append("candidate_rect=%s" % (f["candidate"],))
    return " ".join(parts)


def report():
    """给用户复制用的多行诊断文本。"""
    lines = ["[输入跟随诊断]"]
    if not stats["queries"]:
        lines.append("尚未进行过探测（在任意文本框里敲几个键后再试）。")
        return "\n".join(lines)
    avg = sum(_durations) / len(_durations) if _durations else 0.0
    worst = max(_durations) if _durations else 0.0
    lines.append("探测次数 %d，成功 %d，最近 %d 次平均 %.1f ms，最长 %.1f ms"
                 % (stats["queries"], stats["ok"], len(_durations), avg, worst))
    lines.append("插入符来源：" + ", ".join(
        "%s=%d" % (k[6:], v) for k, v in sorted(stats.items()) if k.startswith("caret:")))
    lines.append("候选框来源：" + ", ".join(
        "%s=%d" % (k[10:], v) for k, v in sorted(stats.items()) if k.startswith("candidate:")))
    lines.append("最近一次：" + summary_line())
    return "\n".join(lines)
