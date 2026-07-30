# -*- coding: utf-8 -*-
"""桌面宠物 V2 分支（PySide6）：基于 V1（pet.py）的交互动画调整版。

与 V1 的差异：
- 移除待机随机走动（左右平移）与走路起伏；
- 新增呼吸动画：脚底锚定的轻微纵向起伏（横向反相、近似保体积），
  亚像素浮点绘制，循环平滑、无位置漂移；
- 新增头部跟随：鼠标悬停在猫咪身上时，头部绕颈部转轴朝鼠标方向平滑转动
  （限制最大角度），鼠标移出后平滑回正；
- 系统开启"减少动态效果"时，自动关闭呼吸 / 头部跟随 / 点击动画（气泡保留）。

其余与 V1 相同：点击弹语录气泡并轮流触发互动动画（跳跃 → 压扁回弹 → 左右
抖动）、拖拽、滚轮缩放（25%~150%，脚底不动）、右键菜单退出。"""
import ctypes
import math
import os
import sys
import random
import time

from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QRectF
from PySide6.QtGui import (QPixmap, QPainter, QColor, QFont, QFontMetrics,
                           QPainterPath, QImage, QLinearGradient)
from PySide6.QtWidgets import QApplication, QWidget, QMenu

BASE_H = 260          # 100% 缩放时的显示高度
MIN_SCALE, MAX_SCALE = 0.25, 1.50
ZOOM_STEP = 1.08      # 每格滚轮的平滑步进

# 互动动画：点击时按此顺序轮流触发
ANIM_KINDS = ("jump", "squash", "shake")
ANIM_DUR = {"jump": 620, "squash": 520, "shake": 700}   # 毫秒
ANIM_TICK_MS = 15

FRAME_MS = 33         # 呼吸 / 头部跟随的动画帧间隔（约 30fps）

# 呼吸：纵向 ±1.5%、横向反相 ±0.6%（近似保体积），周期 3.4s，脚底锚定
BREATH_PERIOD = 3.4
BREATH_AMP_Y = 0.015
BREATH_AMP_X = 0.006

# 头部跟随（比例均相对整张猫图的宽 / 高）
HEAD_MAX_DEG = 12.0             # 最大转角，避免过度旋转脱离身体
HEAD_GAIN = 0.5                 # 鼠标方位角 → 头部目标角的映射比例
HEAD_TAU = 0.12                 # 角度平滑时间常数（秒）
HEAD_PIVOT = (0.66, 0.34)       # 颈部转轴位置
HEAD_CORE_X, HEAD_CORE_Y = 0.44, 0.30   # 头部核心区边界（身体图在此区内抠空）
HEAD_BAND_X, HEAD_BAND_Y = 0.08, 0.08   # 左 / 下羽化过渡带宽度（原位皮毛垫底遮缝）
ERASE_MX, ERASE_MY = 0.07, 0.06         # 抠空区边缘的渐变余量：转头后由静态皮毛补位

SPI_GETCLIENTAREAANIMATION = 0x1042

QUOTES = [
    "喵~ 今天也要加油鸭！",
    "本喵盯着你工作呢，别摸鱼！",
    "铲屎官，罐罐时间到了吗？",
    "刚睡醒，梦见一条大鱼……",
    "摸我可以，但要付猫粮。",
    "你的代码有 bug 的味道。",
    "晒太阳的日子最舒服啦~",
    "陪本喵玩一会儿嘛！",
    "喵生苦短，及时打盹。",
    "今天的你也很好看哦~",
    "工作再忙，也要记得喝水！",
    "本喵才是这台电脑的主人。",
]


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def query_reduced_motion():
    """读取系统"减少动态效果"（Windows 的客户区动画开关）；查询失败按未开启处理。"""
    if sys.platform != "win32":
        return False
    try:
        enabled = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0)
        return bool(ok) and not enabled.value
    except Exception:
        return False


class Bubble(QWidget):
    """对话气泡：圆角白底 + 小尾巴，逐像素透明，2 秒自动消失。"""
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool
                         | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.text = ""
        self.tail_down = True   # 尾巴朝下（气泡在猫上方）
        self.tail_x = 0.5       # 尾巴水平位置（0~1）
        self.font = QFont("Microsoft YaHei", 11)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    PAD_X, PAD_Y, TAIL = 14, 9, 10

    def popup(self, text, anchor_x, anchor_y, above, screen):
        """anchor 为尾巴尖端应指向的点；above=True 表示气泡显示在锚点上方。"""
        self.text = text
        fm = QFontMetrics(self.font)
        tw = min(fm.horizontalAdvance(text), 260)
        rect = fm.boundingRect(0, 0, tw, 1000, Qt.TextWordWrap, text)
        w = rect.width() + self.PAD_X * 2
        h = rect.height() + self.PAD_Y * 2 + self.TAIL
        self.tail_down = above
        x = anchor_x - w // 2
        x = max(screen.left() + 4, min(x, screen.right() - w - 4))
        self.tail_x = min(0.9, max(0.1, (anchor_x - x) / w))
        y = anchor_y - h if above else anchor_y
        self.setGeometry(x, y, w, h)
        self.show()
        self.update()
        self.timer.start(2000)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h, t = self.width(), self.height(), self.TAIL
        body = QRectF(0, 0 if self.tail_down else t, w, h - t)
        path = QPainterPath()
        path.addRoundedRect(body, 12, 12)
        # 小尾巴三角
        tx = self.tail_x * w
        if self.tail_down:
            path.moveTo(tx - 8, body.bottom()); path.lineTo(tx, h); path.lineTo(tx + 8, body.bottom())
        else:
            path.moveTo(tx - 8, body.top()); path.lineTo(tx, 0); path.lineTo(tx + 8, body.top())
        path.closeSubpath()
        p.setPen(QColor(180, 150, 120))
        p.setBrush(QColor(255, 252, 245, 242))
        p.drawPath(path)
        p.setPen(QColor(80, 60, 45))
        p.setFont(self.font)
        p.drawText(body.adjusted(self.PAD_X, self.PAD_Y, -self.PAD_X, -self.PAD_Y),
                   Qt.AlignCenter | Qt.TextWordWrap, self.text)


class Pet(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)   # 无按键悬停也接收 mouseMove，用于头部跟随

        self.src = QPixmap(resource_path("cat_soft.png"))   # 高清羽化素材
        self.scale = 1.0
        self.dragging = False
        self.drag_offset = QPoint()
        self._press_pos = None

        # 互动动画状态
        self.anim_kind = None
        self.anim_t = 0.0
        self.anim_index = 0
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(ANIM_TICK_MS)
        self.anim_timer.timeout.connect(self._anim_tick)

        # 呼吸 / 头部跟随状态
        self.reduced_motion = query_reduced_motion()
        self.t0 = time.monotonic()
        self.head_angle = 0.0     # 当前头部角度（度，正值向右倾）
        self.head_target = 0.0
        self.hover_pos = None     # 悬停时的窗口内坐标；None 表示不在窗口内

        self._build_layers()
        self._rebuild_pixmap()

        scr = QApplication.primaryScreen().availableGeometry()
        self.screen_rect = scr
        self._apply_geometry(scr.center().x(), scr.bottom() + 1)

        self.bubble = Bubble()

        self.menu = QMenu()
        self.menu.addAction("退出", QApplication.quit)

        # 动画帧驱动（呼吸 + 头部角度平滑）；减少动态效果时自动静默
        self.frame_timer = QTimer(self)
        self.frame_timer.timeout.connect(self._frame)
        self.frame_timer.start(FRAME_MS)

        # 定期复查系统"减少动态效果"开关，随系统设置即时降级 / 恢复
        self.rm_timer = QTimer(self)
        self.rm_timer.timeout.connect(self._poll_reduced_motion)
        self.rm_timer.start(4000)

    # ---------- 头 / 身分层 ----------
    def _build_layers(self):
        """按原图分辨率把猫图拆成 body（头部核心区抠空）与 head（左 / 下边羽化）。
        0° 时 head 叠回 body 逐像素还原原图；转头时过渡带的原位皮毛垫底遮住接缝。
        只在启动时做一次，缩放时直接对两层按高度重采样。"""
        src = self.src.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
        w, h = src.width(), src.height()
        core_x = round(w * HEAD_CORE_X)
        core_y = round(h * HEAD_CORE_Y)
        band_x = round(w * HEAD_BAND_X)
        band_y = round(h * HEAD_BAND_Y)

        body = QImage(src)
        # 抠空蒙版：核心区内部全抠、左 / 下边缘按渐变过渡到不抠。
        # 转头让头层移开时，边缘处保留的静态皮毛垫底补位，避免露出直线接缝。
        mw, mh = w - core_x, core_y
        mx = round(w * ERASE_MX)
        my = round(h * ERASE_MY)
        mask = QImage(mw, mh, QImage.Format_ARGB32_Premultiplied)
        mask.fill(0)
        p = QPainter(mask)
        gx = QLinearGradient(0, 0, mx, 0)
        gx.setColorAt(0.0, QColor(0, 0, 0, 0))
        gx.setColorAt(1.0, QColor(0, 0, 0, 255))
        p.fillRect(0, 0, mx, mh, gx)
        p.fillRect(mx, 0, mw - mx, mh, QColor(0, 0, 0, 255))
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        gy = QLinearGradient(0, mh - my, 0, mh)
        gy.setColorAt(0.0, QColor(0, 0, 0, 255))
        gy.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, mh - my, mw, my, gy)
        p.end()
        p = QPainter(body)
        p.setCompositionMode(QPainter.CompositionMode_DestinationOut)
        p.drawImage(core_x, 0, mask)
        p.end()

        crop_x = core_x - band_x
        crop_h = core_y + band_y
        head = src.copy(crop_x, 0, w - crop_x, crop_h)
        p = QPainter(head)
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        gx = QLinearGradient(0, 0, band_x, 0)
        gx.setColorAt(0.0, QColor(0, 0, 0, 0))
        gx.setColorAt(1.0, QColor(0, 0, 0, 255))
        p.fillRect(0, 0, band_x, crop_h, gx)
        gy = QLinearGradient(0, core_y, 0, crop_h)
        gy.setColorAt(0.0, QColor(0, 0, 0, 255))
        gy.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, core_y, head.width(), crop_h - core_y, gy)
        p.end()

        self.body_src = QPixmap.fromImage(body)
        self.head_src = QPixmap.fromImage(head)
        self.head_x_frac = crop_x / w    # head 层在整图中的水平起点比例
        self.head_h_frac = crop_h / h    # head 层高度占整图比例

    # ---------- 素材缩放与窗口几何 ----------
    def _rebuild_pixmap(self):
        hpx = round(BASE_H * self.scale)
        self.pix = self.src.scaledToHeight(hpx, Qt.SmoothTransformation)
        self.body_pix = self.body_src.scaledToHeight(hpx, Qt.SmoothTransformation)
        head_h = max(1, round(self.head_src.height() * hpx / self.src.height()))
        self.head_pix = self.head_src.scaledToHeight(head_h, Qt.SmoothTransformation)
        # 窗口内为动画预留的空间：头顶留跳跃高度，左右留抖动/压扁/转头的余量
        self.top_pad = round(self.pix.height() * 0.32)
        self.side_pad = round(self.pix.width() * 0.15)

    def _apply_geometry(self, foot_x, foot_y):
        """按当前素材重设窗口尺寸，并保持脚底中心位于 (foot_x, foot_y)。"""
        w = self.pix.width() + 2 * self.side_pad
        h = self.pix.height() + self.top_pad + 6
        self.resize(w, h)
        self.move(foot_x - w // 2, foot_y - h)

    def _set_scale(self, new_scale):
        foot_x = self.x() + self.width() // 2
        foot_y = self.y() + self.height()
        self.scale = new_scale
        self._rebuild_pixmap()
        self._apply_geometry(foot_x, foot_y)

    # ---------- 呼吸 / 头部跟随 ----------
    def _breath_scales(self, t):
        """呼吸缩放系数 (宽, 高)：纵向正弦起伏、横向轻微反相；减少动态效果时恒 1。"""
        if self.reduced_motion:
            return 1.0, 1.0
        ph = math.sin(2 * math.pi * (t - self.t0) / BREATH_PERIOD)
        return 1.0 - BREATH_AMP_X * ph, 1.0 + BREATH_AMP_Y * ph

    def _cat_rect(self):
        """当前猫咪主体（未叠加动画形变）的窗口内矩形。"""
        return QRect((self.width() - self.pix.width()) // 2,
                     self.height() - self.pix.height() - 3,
                     self.pix.width(), self.pix.height())

    def _update_head_target(self):
        """按鼠标相对颈部转轴的方位更新头部目标角；不悬停 / 拖拽 / 降级时回正。"""
        if (self.reduced_motion or self.dragging or self.hover_pos is None
                or not self._cat_rect().contains(self.hover_pos)):
            self.head_target = 0.0
            return
        r = self._cat_rect()
        px = r.x() + r.width() * HEAD_PIVOT[0]
        py = r.y() + r.height() * HEAD_PIVOT[1]
        dx = self.hover_pos.x() - px
        dy = self.hover_pos.y() - py
        ang = math.degrees(math.atan2(dx, max(8.0, -dy))) * HEAD_GAIN
        self.head_target = max(-HEAD_MAX_DEG, min(HEAD_MAX_DEG, ang))

    def _frame(self):
        """帧驱动：头部角度指数趋近目标 + 呼吸重绘；无动画需求时不重绘。"""
        self._update_head_target()
        if self.reduced_motion:
            # 减少动态效果：头部立即回正（不做平滑过渡），静止后不再重绘
            if self.head_angle == 0.0:
                return
            self.head_angle = 0.0
            self.update()
            return
        k = 1.0 - math.exp(-FRAME_MS / 1000.0 / HEAD_TAU)
        self.head_angle += (self.head_target - self.head_angle) * k
        if abs(self.head_angle - self.head_target) < 0.02:
            self.head_angle = self.head_target
        self.update()

    def _poll_reduced_motion(self):
        rm = query_reduced_motion()
        if rm != self.reduced_motion:
            self.reduced_motion = rm
            if rm:
                self.head_target = 0.0
                self.head_angle = 0.0
                self.anim_kind = None
                self.anim_timer.stop()
            else:
                self.t0 = time.monotonic()   # 呼吸从静止相位平滑起步
            self.update()

    # ---------- 互动动画 ----------
    def play_anim(self):
        """点击时轮流触发：跳跃 → 压扁回弹 → 左右抖动；减少动态效果时跳过。"""
        if self.reduced_motion:
            return
        self.anim_kind = ANIM_KINDS[self.anim_index % len(ANIM_KINDS)]
        self.anim_index += 1
        self.anim_t = 0.0
        self.anim_timer.start()

    def _anim_tick(self):
        self.anim_t += ANIM_TICK_MS / ANIM_DUR[self.anim_kind]
        if self.anim_t >= 1.0:
            self.anim_kind = None
            self.anim_timer.stop()
        self.update()

    def _anim_offsets(self):
        """当前动画帧的绘制参数：(水平偏移, 抬升高度, 宽度系数, 高度系数)。"""
        k, t = self.anim_kind, self.anim_t
        if k == "jump":
            # 抛物线：t=0.5 时到达最高点
            return 0.0, self.pix.height() * 0.30 * 4 * t * (1 - t), 1.0, 1.0
        if k == "squash":
            if t < 0.35:            # 压下去
                sy = 1 - 0.38 * math.sin(t / 0.35 * math.pi / 2)
            else:                   # 弹回来，带轻微过冲
                u = (t - 0.35) / 0.65
                sy = 1 - 0.38 * math.exp(-4 * u) * math.cos(u * 1.5 * math.pi)
            return 0.0, 0.0, 1 + (1 - sy) * 0.6, sy   # 压扁时变宽，近似保体积
        if k == "shake":
            # 衰减正弦：3 个来回，幅度递减
            amp = self.pix.width() * 0.055
            return amp * math.exp(-3 * t) * math.sin(t * 6 * math.pi), 0.0, 1.0, 1.0
        return 0.0, 0.0, 1.0, 1.0

    # ---------- 绘制 ----------
    def _layout(self, t=None):
        """当前帧猫咪整体的目标矩形（浮点，亚像素）：脚底锚定 + 动画/呼吸形变。"""
        dx, dy, sx, sy = self._anim_offsets()
        bx, by = self._breath_scales(time.monotonic() if t is None else t)
        tw = self.pix.width() * sx * bx
        th = self.pix.height() * sy * by
        x = (self.width() - tw) / 2 + dx
        y = self.height() - th - 3 - dy
        return QRectF(x, y, tw, th)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = self._layout()
        p.drawPixmap(r, self.body_pix, QRectF(self.body_pix.rect()))
        # 头部层：绕颈部转轴旋转后叠回身体（0° 时逐像素还原原图）
        px = r.x() + r.width() * HEAD_PIVOT[0]
        py = r.y() + r.height() * HEAD_PIVOT[1]
        p.save()
        p.translate(px, py)
        p.rotate(self.head_angle)
        p.translate(-px, -py)
        head_rect = QRectF(r.x() + r.width() * self.head_x_frac, r.y(),
                           r.width() * (1 - self.head_x_frac),
                           r.height() * self.head_h_frac)
        p.drawPixmap(head_rect, self.head_pix, QRectF(self.head_pix.rect()))
        p.restore()

    # ---------- 互动 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.dragging = True
            self._press_pos = e.globalPosition().toPoint()
            self.drag_offset = self._press_pos - self.pos()

    def mouseMoveEvent(self, e):
        self.hover_pos = e.position().toPoint()
        if self.dragging:
            self.move(e.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.dragging = False
            # 位移很小视为点击 → 弹气泡 + 轮流触发互动动画
            if self._press_pos is not None and \
               (e.globalPosition().toPoint() - self._press_pos).manhattanLength() < 6:
                self.say(random.choice(QUOTES))
                self.play_anim()
            self._press_pos = None

    def leaveEvent(self, _):
        self.hover_pos = None   # 头部由 _frame 平滑回正

    def contextMenuEvent(self, e):
        self.menu.exec(e.globalPos())

    def _current_screen_rect(self):
        """宠物当前所在屏幕的可用区域；拖到副屏后气泡应按副屏定位。"""
        scr = self.screen() or QApplication.primaryScreen()
        return scr.availableGeometry()

    def say(self, text):
        self.screen_rect = self._current_screen_rect()
        head_y = self.y() + self.height() - self.pix.height()   # 猫头顶
        anchor_x = self.x() + self.width() // 2
        # 窗口顶部距屏幕顶部太近时改到下方（用窗口位置而非猫头顶，
        # 因为 top_pad 留白会让猫头顶始终距屏幕顶有 ~89px，导致贴顶时阈值不触发）
        above = self.y() - 80 > self.screen_rect.top()
        anchor_y = head_y - 6 if above else self.y() + self.height() + 6
        self.bubble.popup(text, anchor_x, anchor_y, above, self.screen_rect)

    # ---------- 滚轮缩放：脚底位置不动 ----------
    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if dy == 0:   # 纯横向滚动（触控板/倾斜滚轮）不缩放
            return
        factor = ZOOM_STEP if dy > 0 else 1 / ZOOM_STEP
        new_scale = min(MAX_SCALE, max(MIN_SCALE, self.scale * factor))
        if abs(new_scale - self.scale) < 1e-4:
            return
        self._set_scale(new_scale)
        self.update()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    pet = Pet()
    pet.show()
    sys.exit(app.exec())
