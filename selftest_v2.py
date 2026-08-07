# -*- coding: utf-8 -*-
"""pet_v2 offscreen 自测：分层还原、无待机平移、呼吸、头部跟随、减少动态效果、闲置提醒、V1 回归"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import math
import sys
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
import pet_v2 as m

app = QApplication(sys.argv)
p = m.Pet()
p.show()
p.reduced_motion = False   # 测试机的系统设置不应影响用例
assert not p.src.isNull(), "cat_soft.png load failed"
print("sprite:", p.src.width(), "x", p.src.height(), "| display:", p.pix.width(), "x", p.pix.height())

# ---------- 输入光标跟随：安全位置几何契约 ----------
screen = QRect(0, 0, 1280, 720)
caret = QRect(500, 300, 2, 20)
focus = QRect(450, 280, 220, 45)
candidate = QRect(470, 325, 280, 80)
pos = m._input_safe_position(caret, focus, candidate, QSize(60, 52), screen)
pet_rect = QRect(pos, QSize(60, 52))
assert not pet_rect.intersects(focus)
assert not pet_rect.intersects(candidate)
assert screen.contains(pet_rect)

wechat_screen = QRect(0, 0, 864, 316)
wechat_caret = QRect(226, 105, 2, 22)
wechat_candidate = QRect(216, 134, 572, 44)
wechat_pos = m._input_safe_position(
    wechat_caret, QRect(0, 0, 864, 316), wechat_candidate,
    QSize(60, 52), wechat_screen)
wechat_pet = QRect(wechat_pos, QSize(60, 52))
wechat_avoid = wechat_candidate.adjusted(-m.INPUT_GAP, -m.INPUT_GAP,
                                          m.INPUT_GAP, m.INPUT_GAP)
assert not wechat_pet.intersects(wechat_avoid)
assert wechat_pet.right() < wechat_candidate.left()
assert abs(wechat_pet.center().y() - wechat_caret.center().y()) <= 1

# 文档编辑器通常把整页暴露为焦点控件；不能因此把宠物推到页面底部。
document_focus = QRect(10, 20, 875, 810)
document_caret = QRect(142, 104, 2, 26)
document_pos = m._input_safe_position(
    document_caret, document_focus, None, QSize(60, 52), QRect(0, 0, 906, 855))
assert document_pos.y() == document_caret.bottom() + m.INPUT_GAP + 1
assert abs(document_pos.x() + 30 - document_caret.center().x()) <= 1

edge = m._input_safe_position(QRect(1268, 690, 2, 20), QRect(1200, 680, 79, 39), None,
                              QSize(60, 52), screen)
assert screen.contains(QRect(edge, QSize(60, 52)))
print("input-follow geometry: safe placement and screen clamping contract OK")

# IMM CANDIDATEFORM rectangles are already screen coordinates.  Keep a
# non-zero target-window origin in this fixture so an accidental
# ClientToScreen conversion would be observable.
candidate_form = m.CANDIDATEFORM()
candidate_form.rcArea.left = 720
candidate_form.rcArea.top = 410
candidate_form.rcArea.right = 980
candidate_form.rcArea.bottom = 510
assert m._candidate_form_rect(candidate_form) == QRect(720, 410, 260, 100)
candidate_form.ptCurrentPos.x = 720
candidate_form.ptCurrentPos.y = 410
candidate_form.rcArea.right = candidate_form.rcArea.left
candidate_form.rcArea.bottom = candidate_form.rcArea.top
assert m._candidate_form_rect(candidate_form).topLeft() == QPoint(720, 410)
print("input-follow IME coordinates: screen-space contract OK")

wechat_windows = [
    ("wetype_renderer.exe", QRect(216, 134, 572, 44)),
    ("wetype_server.exe", QRect(216, 134, 572, 44)),
    ("wetype_renderer.exe", QRect(1400, 700, 500, 44)),
    ("other_overlay.exe", QRect(210, 130, 580, 50)),
]
wechat_caret = QRect(226, 105, 2, 22)
assert m._select_wechat_candidate(wechat_caret, wechat_windows) == QRect(216, 134, 572, 44)
assert m._select_wechat_candidate(
    wechat_caret, [("wetype_renderer.exe", QRect(216, 134, 20, 10))]) is None
assert m._select_wechat_candidate(
    wechat_caret, [("wetype.exe", QRect(216, 134, 572, 44))]) == QRect(216, 134, 572, 44)
assert m._select_wechat_candidate(
    wechat_caret, [("ChsIME.exe", QRect(216, 134, 572, 44))]) == QRect(216, 134, 572, 44)
assert m._select_wechat_candidate(
    wechat_caret, [("__generic_popup__", QRect(216, 134, 572, 44))]) == QRect(216, 134, 572, 44)
assert m._is_generic_popup_style(m.WS_POPUP, m.WS_EX_TOOLWINDOW)
assert not m._is_generic_popup_style(m.WS_POPUP | m.WS_CAPTION, m.WS_EX_TOOLWINDOW)

class FailingUser32:
    def IsWindowVisible(self, _hwnd):
        raise RuntimeError("callback failure")

    def EnumWindows(self, callback, _lparam):
        callback(123, 0)
        return True


old_configure = m._configure_input_apis
old_user32 = m.ctypes.windll.user32
m._configure_input_apis = lambda: True
m.ctypes.windll.user32 = FailingUser32()
try:
    assert m._wechat_candidate_rect(wechat_caret) is None
finally:
    m._configure_input_apis = old_configure
    m.ctypes.windll.user32 = old_user32

# ---------- 输入光标跟随：Pet 状态切换与脚底锚定 ----------
from PySide6.QtCore import QEvent, QPointF
from PySide6.QtGui import QFocusEvent, QMouseEvent, QWheelEvent

assert m.INPUT_IDLE_MS == 1000
old_query = m.query_input_context
saved_scale = p.scale
saved_foot = (p.x() + p.width() // 2, p.y() + p.height())
m.query_input_context = lambda: m.InputContext(
    QRect(300, 200, 2, 20), QRect(250, 180, 140, 45), None,
    QRect(0, 0, 1280, 720))
try:
    def input_on():
        p._input_on_key()
        assert p.input_follow_active and abs(p.scale - saved_scale * 0.2) < 1e-9

    def input_off():
        assert not p.input_follow_active and abs(p.scale - saved_scale) < 1e-9
        assert (p.x() + p.width() // 2, p.y() + p.height()) == saved_foot

    # 输入跟随是独立功能，键盘互动与减少动态效果均不应阻止它启动。
    p.act_kb.setChecked(False)
    p.reduced_motion = True
    input_on()
    p._stop_input_follow()
    input_off()
    p.reduced_motion = False
    p.act_kb.setChecked(True)

    input_on()
    active_scale = p.scale
    p._input_on_key()
    assert p.input_saved_scale == saved_scale and p.scale == active_scale
    p._stop_input_follow()
    input_off()

    # 每个用户交互退出路径都必须还原缩放和脚底锚点。
    input_on()
    click = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(5, 5),
                        QPointF(p.x() + 5, p.y() + 5), Qt.LeftButton,
                        Qt.LeftButton, Qt.NoModifier)
    p.mousePressEvent(click)
    p.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(5, 5),
                                    QPointF(p.x() + 5, p.y() + 5), Qt.LeftButton,
                                    Qt.NoButton, Qt.NoModifier))
    input_off()

    input_on()
    p.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(5, 5),
                                  QPointF(p.x() + 5, p.y() + 5), Qt.LeftButton,
                                  Qt.LeftButton, Qt.NoModifier))
    input_off()
    p.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(25, 25),
                                    QPointF(p.x() + 25, p.y() + 25), Qt.LeftButton,
                                    Qt.NoButton, Qt.NoModifier))

    input_on()
    p.wheelEvent(QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 0),
                             Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
    input_off()

    input_on()
    p.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    input_off()

    m.query_input_context = lambda: None
    p._input_on_key()
    assert not p.input_follow_active and p.scale == saved_scale
    assert (p.x() + p.width() // 2, p.y() + p.height()) == saved_foot
finally:
    m.query_input_context = old_query
print("input-follow state: activation, idempotence, restore and foot anchor contract OK")

# ---------- 待机不再左右平移 ----------
assert not hasattr(p, "vx") and not hasattr(p, "behave"), "walk logic should be removed"
pos0 = (p.x(), p.y())
for _ in range(200):
    p._frame()
assert (p.x(), p.y()) == pos0, "idle must not move the window"
print("idle: no horizontal walk, window position fixed OK")

# ---------- 呼吸：幅度、连续性、脚底/中心锚定 ----------
t0 = p.t0
vals = [p._breath_scales(t0 + i * 0.033) for i in range(240)]   # 约 2.3 个周期
bys = [by for _, by in vals]
assert max(bys) <= 1 + m.BREATH_AMP_Y + 1e-9 and min(bys) >= 1 - m.BREATH_AMP_Y - 1e-9
assert max(bys) > 1 + m.BREATH_AMP_Y * 0.95 and min(bys) < 1 - m.BREATH_AMP_Y * 0.95
for a, b in zip(bys, bys[1:]):
    assert abs(b - a) < 0.002, "breathing must be continuous (no frame jump)"
for i in range(0, 240, 17):
    r = p._layout(t0 + i * 0.033)
    assert abs(r.bottom() - (p.height() - p.bottom_pad - 3)) < 1e-6, "feet must stay anchored"
    assert abs(r.center().x() - p.width() / 2) < 1e-6, "no horizontal drift"
amp_px = p.pix.height() * m.BREATH_AMP_Y
print(f"breath: ±{m.BREATH_AMP_Y*100:.1f}% (~{amp_px:.1f}px), continuous, foot/center anchored OK")

# ---------- 头部跟随：方向、限幅、平滑、复位 ----------
r = p._cat_rect()
def hover(fx, fy):
    p.hover_pos = QPoint(round(r.x() + r.width() * fx), round(r.y() + r.height() * fy))
    p._update_head_target()
    return p.head_target

assert hover(0.90, 0.10) > 2, "mouse right of pivot -> head turns right"
assert hover(0.10, 0.10) < -2, "mouse left of pivot -> head turns left"
assert hover(0.99, 0.95) == m.HEAD_MAX_DEG, "far corner clamps to +max"
assert hover(0.01, 0.95) == -m.HEAD_MAX_DEG, "far corner clamps to -max"
assert abs(hover(0.66, 0.05)) < 1.5, "above pivot -> nearly straight"

p.hover_pos = QPoint(round(r.x() + r.width() * 0.9), round(r.y() + r.height() * 0.2))
angles = []
for _ in range(120):
    p._frame()
    angles.append(p.head_angle)
target = p.head_target
assert abs(angles[-1] - target) < 0.05, (angles[-1], target)
assert all(b >= a - 1e-9 for a, b in zip(angles, angles[1:])), "approach must be monotonic"
step_max = max(abs(b - a) for a, b in zip(angles, angles[1:]))
assert step_max < target * 0.35, "no snapping, smooth approach"
p.hover_pos = None          # 鼠标移出 → 平滑回正
for _ in range(150):
    p._frame()
assert abs(p.head_angle) < 0.05, p.head_angle
print(f"head: direction/clamp(±{m.HEAD_MAX_DEG}°)/smooth(max step {step_max:.2f}°)/reset OK")

# 窗口内但在猫身外（留白区）不应触发；拖拽中不跟随
assert hover(-0.04, 0.5) == 0.0 if r.x() > 0 else True
p.hover_pos = QPoint(2, 2); p._update_head_target()
assert p.head_target == 0.0, "padding area must not trigger head turn"
p.dragging = True; hover(0.9, 0.2); assert p.head_target == 0.0, "no head turn while dragging"
p.dragging = False

# ---------- 减少动态效果：呼吸/头部/点击动画降级，气泡保留 ----------
p.reduced_motion = True
assert p._breath_scales(t0 + 1.7) == (1.0, 1.0)
assert hover(0.9, 0.2) == 0.0
p.play_anim()
assert p.anim_kind is None and not p.anim_timer.isActive(), "click anim skipped"
p.say("降级模式也要说话")
assert p.bubble.isVisible(), "bubble must survive reduced motion"

# 开启时头部必须立即归零（不能只清 target 后继续平滑旋转）
p.head_angle = 7.5
p._frame()
assert p.head_angle == 0.0, "reduced motion must zero head_angle immediately"
# 系统开关轮询路径同样立即归零
p.reduced_motion = False
p.head_angle = 5.0
_orig_qrm = m.query_reduced_motion
m.query_reduced_motion = lambda: True
p._poll_reduced_motion()
m.query_reduced_motion = _orig_qrm
assert p.reduced_motion and p.head_angle == 0.0 and p.head_target == 0.0, \
    "poll path must zero head_angle immediately"
p.reduced_motion = False
print("reduced-motion: breath/head/click-anim off, head snaps to 0, bubble kept OK")

# ---------- 0° 头身分层应还原原图 ----------
p.anim_kind = None
p.reduced_motion = True     # 冻结呼吸，布局为整数矩形
p.act_kb.setChecked(False)  # 键盘会画在猫脚前，先关掉再逐像素比对
img = QImage(p.size(), QImage.Format_ARGB32)
img.fill(0)
p.render(img)
ref = p.pix.toImage().convertToFormat(QImage.Format_ARGB32)
ox, oy = p.side_pad, p.height() - p.bottom_pad - p.pix.height() - 3
total = bad = 0
for j in range(0, ref.height(), 5):
    for i in range(0, ref.width(), 5):
        pa = ref.pixelColor(i, j)
        pb = img.pixelColor(ox + i, oy + j)
        if pa.alpha() < 8 and pb.alpha() < 8:
            continue
        total += 1
        if (abs(pa.alpha() - pb.alpha()) > 40 or abs(pa.red() - pb.red()) > 45
                or abs(pa.green() - pb.green()) > 45 or abs(pa.blue() - pb.blue()) > 45):
            bad += 1
assert total > 800, total
assert bad / total < 0.02, f"composite mismatch {bad}/{total}"
print(f"split layers reconstruct original at 0°: {bad}/{total} outliers OK")
p.act_kb.setChecked(True)
p.reduced_motion = False

# ---------- V1 回归：缩放锚点 / 气泡 / 互动动画 ----------
for target in (0.25, 1.5):
    foot = (p.x() + p.width() // 2, p.y() + p.height())
    p._set_scale(target)
    foot2 = (p.x() + p.width() // 2, p.y() + p.height())
    assert abs(foot[0] - foot2[0]) <= 1 and foot[1] == foot2[1], (foot, foot2)
p._set_scale(1.0)
print("zoom keeps foot anchor OK")

# ---------- 滚轮：纵向缩放，纯横向事件忽略 ----------
from PySide6.QtCore import QPointF
from PySide6.QtGui import QWheelEvent

def wheel(ax, ay):
    ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(ax, ay),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    p.wheelEvent(ev)

s0 = p.scale
wheel(120, 0)
assert p.scale == s0, "horizontal-only wheel must not change scale"
wheel(-120, 0)
assert p.scale == s0, "horizontal-only wheel must not change scale"
wheel(0, 120)
assert p.scale > s0, "wheel up should zoom in"
wheel(0, -120)
assert abs(p.scale - s0) < 1e-9, "wheel down should zoom out"
print("wheel: vertical zooms, horizontal-only ignored OK")

# ---------- 闲置提醒：到时自动弹语录并重新计时，互动重置 ----------
assert p.idle_timer.isActive() and p.idle_timer.isSingleShot(), "idle timer runs from startup"
assert m.IDLE_MIN_MS <= p.idle_timer.interval() <= m.IDLE_MAX_MS, p.idle_timer.interval()
p.bubble.hide()
p._idle_chatter()
assert p.bubble.isVisible() and p.bubble.text in m.QUOTES, "idle pops a quote from QUOTES"
assert p.idle_timer.isActive(), "idle chatter must reschedule itself"
p.bubble.hide()
p.dragging = True
p._idle_chatter()
assert not p.bubble.isVisible(), "no idle bubble while dragging"
assert p.idle_timer.isActive(), "must keep rescheduling while dragging"
p.dragging = False
p.idle_timer.stop()
wheel(0, 120)               # 任一互动都应重启计时（这里用滚轮验证）
assert p.idle_timer.isActive(), "interaction must restart idle timer"
wheel(0, -120)              # 恢复缩放，避免影响后续用例
prev = p._pick_quote()
for _ in range(40):
    q = p._pick_quote()
    assert q in m.QUOTES and q != prev, "random quote must not repeat back-to-back"
    prev = q
print("idle chatter: auto quote, reschedule, interaction reset, no back-to-back repeat OK")

# ---------- 气泡按宠物当前所在屏幕定位 ----------
from PySide6.QtCore import QRect
p.screen_rect = QRect(-9999, -9999, 10, 10)   # 污染缓存，模拟启动后被拖去别的屏幕
p.say("屏幕定位测试")
assert p.screen_rect == p.screen().availableGeometry(), \
    "say() must refresh from the pet's current screen, not a startup cache"
print("bubble uses current screen geometry OK")

p.say("测试一条比较长的语录，看看自动换行和居中效果如何。")
assert p.bubble.isVisible() and p.bubble.timer.isActive()
p.move(p.x(), p.screen_rect.top() - p.top_pad)
p.say("顶部测试")
assert not p.bubble.tail_down, "near-top should flip below"
print("bubble + near-top flip OK")

kinds = []
for _ in range(4):
    p.play_anim()
    kinds.append(p.anim_kind)
    p.anim_kind = None; p.anim_timer.stop()
assert kinds == ["jump", "squash", "shake", "jump"], kinds

def offsets_at(kind, t):
    p.anim_kind, p.anim_t = kind, t
    return p._anim_offsets()

dx, dy, sx, sy = offsets_at("jump", 0.5)
assert abs(dy - p.pix.height() * 0.30) < 1 and dx == 0 and sx == sy == 1.0
dx, dy, sx, sy = offsets_at("squash", 0.35)
assert abs(sy - 0.62) < 0.01 and abs(sx - 1.228) < 0.01
assert p.pix.width() * 1.228 <= p.pix.width() + 2 * p.side_pad
first = max(abs(offsets_at("shake", t / 100)[0]) for t in range(0, 34))
assert first <= p.side_pad
p.anim_kind = None
p.play_anim()
for _ in range(200):
    p._anim_tick()
    if p.anim_kind is None:
        break
assert p.anim_kind is None and not p.anim_timer.isActive()
assert p._anim_offsets() == (0.0, 0.0, 1.0, 1.0)
print("click anims (jump/squash/shake) regression OK")

# 转头极限时也不越出窗口（头层四角绕轴旋转后仍在窗口内）
rr = p._layout(p.t0)
pxv = rr.x() + rr.width() * m.HEAD_PIVOT[0]
pyv = rr.y() + rr.height() * m.HEAD_PIVOT[1]
hx0 = rr.x() + rr.width() * p.head_x_frac
corners = [(hx0, rr.y()), (rr.right(), rr.y()),
           (hx0, rr.y() + rr.height() * p.head_h_frac), (rr.right(), rr.y() + rr.height() * p.head_h_frac)]
for deg in (m.HEAD_MAX_DEG, -m.HEAD_MAX_DEG):
    a = math.radians(deg)
    for cx, cy in corners:
        x = pxv + (cx - pxv) * math.cos(a) - (cy - pyv) * math.sin(a)
        y = pyv + (cx - pxv) * math.sin(a) + (cy - pyv) * math.cos(a)
        assert -1 <= x <= p.width() + 1 and -1 <= y <= p.height() + 1, (deg, x, y)
print("rotated head stays inside window at ±max angle OK")

# ---------- 右键菜单：置顶 / 自动走动开关 + 退出 ----------
labels = [a.text() for a in p.menu.actions() if a.text()]
assert labels == ["始终置顶", "自动走动", "键盘互动", "退出"], labels
assert p.act_topmost.isChecked() and bool(p.windowFlags() & Qt.WindowStaysOnTopHint)
p.act_topmost.setChecked(False)
app.processEvents()     # show 延后到事件循环，先跑一轮
assert not (p.windowFlags() & Qt.WindowStaysOnTopHint), "uncheck must drop topmost flag"
assert not (p.bubble.windowFlags() & Qt.WindowStaysOnTopHint), "bubble must follow topmost state"
assert p.isVisible(), "window must stay visible after flag change"
p.act_topmost.setChecked(True)
app.processEvents()
assert p.windowFlags() & Qt.WindowStaysOnTopHint, "recheck must restore topmost flag"
assert p.bubble.windowFlags() & Qt.WindowStaysOnTopHint
assert p.isVisible()
print("menu: topmost toggle updates pet+bubble flags, window stays visible OK")

# ---------- 自动走动：默认关闭、区域=右下 1/4、目标限定、步进收敛 ----------
p.bubble.hide()         # 气泡可见会暂停走动，先收起
assert not p.walk_enabled and not p.walk_timer.isActive() and p.walk_target is None, \
    "auto-walk must default to off"
scr = p._current_screen_rect()
region = p._walk_region()
assert region.left() == scr.center().x() and region.top() == scr.center().y()
assert region.right() == scr.right() and region.bottom() == scr.bottom()

p.act_walk.setChecked(True)
assert p.walk_enabled and p.walk_timer.isActive() and p.walk_target is not None, \
    "enabling walk must start timer and pick a target"
for _ in range(60):     # 随机目标点必须始终落在合法区间（窗口整体不出区域）
    p._pick_walk_target()
    t = p.walk_target
    assert region.left() <= t.x() - p.width() // 2 and t.x() + p.width() // 2 <= region.right() + 1, t
    assert region.top() <= t.y() - p.height() and t.y() <= region.bottom(), t

# 从区域外（左上角）出发也要一步步走回区域内的目标点
p.move(scr.left(), scr.top())
p._pick_walk_target()
target = QPoint(p.walk_target)
step_limit = m.WALK_SPEED * m.WALK_TICK_MS / 1000.0 + 1.5   # 单步位移上限（含取整误差）
prev = (p.x() + p.width() // 2, p.y() + p.height())
for _ in range(5000):
    p._walk_tick()
    cur = (p.x() + p.width() // 2, p.y() + p.height())
    assert math.hypot(cur[0] - prev[0], cur[1] - prev[1]) <= step_limit, "per-tick step too large"
    prev = cur
    if p.walk_target is None:
        break
assert p.walk_target is None, "must converge to target"
assert prev == (target.x(), target.y()), (prev, target)
assert p.walk_pause_timer.isActive(), "must pause before picking next target"
print("walk: bottom-right quadrant only, uniform steps, converges and pauses OK")

# 拖拽 / 气泡显示 / 减少动态效果时暂停走动
p._pick_walk_target()
p.walk_target = QPoint(region.center().x(), region.bottom())
pos = (p.x(), p.y())
p.dragging = True
p._walk_tick()
assert (p.x(), p.y()) == pos, "no walking while dragging"
p.dragging = False
p.reduced_motion = True
p._walk_tick()
assert (p.x(), p.y()) == pos, "no walking under reduced motion"
p.reduced_motion = False
p.bubble.show()
p._walk_tick()
assert (p.x(), p.y()) == pos, "no walking while bubble is visible"
p.bubble.hide()

# 停留计时在暂停态到期不选新目标（停留被冻结），恢复后才选
p.walk_target = None
p.dragging = True
p._on_walk_pause_done()
assert p.walk_target is None, "pause expiry while dragging must not pick a target"
p.dragging = False
p._on_walk_pause_done()
assert p.walk_target is not None, "pause expiry when resumed must pick a target"

# 拖拽结束：丢弃旧目标（可能已跨屏），停留后重选
from PySide6.QtCore import QEvent, QPointF
from PySide6.QtGui import QMouseEvent
p._press_pos = QPoint(-10_000, -10_000)     # 位移够大，不触发点击路径
p.dragging = True
rel = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(5, 5),
                  QPointF(p.x() + 5, p.y() + 5), Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
p.mouseReleaseEvent(rel)
assert not p.dragging and p.walk_target is None and p._walk_pos is None, \
    "drag release must drop stale walk target"
assert p.walk_pause_timer.isActive(), "drag release must schedule a fresh pause"

# 缩放会重新收拢目标点；关闭开关立即停止并清空状态
p.walk_target = QPoint(scr.left() + 5, scr.top() + 5)   # 人为塞一个区域外目标
p._set_scale(0.5)
t = p.walk_target
assert region.left() <= t.x() <= region.right() and region.top() <= t.y() <= region.bottom(), \
    "zoom must re-clamp walk target into region"
p._set_scale(1.0)
p.act_walk.setChecked(False)
assert not p.walk_enabled and not p.walk_timer.isActive()
assert p.walk_target is None and p._walk_pos is None
assert not p.walk_pause_timer.isActive(), "disable must stop pause timer"
print("walk: paused by drag/bubble/reduced-motion, frozen stay, drag re-pick, clean disable OK")

# ---------- 键盘互动：分区选脚、自动重复忽略、按住保持、开关联动留白 ----------
import time as _time
assert p.kb_enabled and p.act_kb.isChecked(), "keyboard interaction defaults on"
assert p.bottom_pad > 0, "keyboard area reserved below the cat"
p._on_global_key(ord('A'), 30)
assert p._held[30] == 0 and p._paw_held[0] == 1, "A is a left-hand key"
p._on_global_key(ord('A'), 30)      # 系统自动重复：不重复计数
assert p._paw_held[0] == 1, "auto-repeat must be ignored"
assert p._paw_progress(0, _time.monotonic()) == 1.0, "paw stays down while held"
p._on_global_key(ord('L'), 38)
assert p._held[38] == 1, "L is a right-hand key"
p._on_global_key_up(ord('A'), 30)
p._on_global_key_up(ord('L'), 38)
assert p._paw_held == [0, 0]
assert p._paw_progress(0, _time.monotonic() + 1.0) == 0.0, "paw lifts back after release"
p._on_global_key_up(ord('Q'), 16)   # 无配对按下的松键：安全忽略
# 同一 vk 不同物理键（主/小键盘 Enter）按 key_id 区分，不互相吞掉
p._on_global_key(0x0D, 28)
p._on_global_key(0x0D, 28 | (1 << 16))
assert p._paw_held[1] == 2, "same vk on two physical keys must both count"
p._on_global_key_up(0x0D, 28)
p._on_global_key_up(0x0D, 28 | (1 << 16))
assert p._paw_held == [0, 0]
sides = []
for _ in range(2):              # 未知分区按键交替用脚
    p._on_global_key(0x20, 57)
    sides.append(p._held[57])
    p._on_global_key_up(0x20, 57)
assert sides[0] != sides[1], sides
p.reduced_motion = True         # 减少动态效果时不响应
p._on_global_key(ord('B'), 48)
assert p._paw_held == [0, 0]
p.reduced_motion = False
foot = (p.x() + p.width() // 2, p.y() + p.height())
p.act_kb.setChecked(False)      # 关闭：留白清零、状态清空、脚底不动
assert p.bottom_pad == 0 and not p._held and p._paw_held == [0, 0]
assert (p.x() + p.width() // 2, p.y() + p.height()) == foot, "toggle keeps foot anchor"
p._on_global_key(ord('C'), 46)
assert p._paw_held == [0, 0], "no response while disabled"
p.act_kb.setChecked(True)
assert p.bottom_pad > 0
p.key_listener.stop()
assert not p.key_listener._thread.is_alive(), "hook thread must exit on stop"
print("keyboard tap: side split, auto-repeat, hold/lift, same-vk keys, toggle, hook shutdown OK")

print("ALL PASS")
