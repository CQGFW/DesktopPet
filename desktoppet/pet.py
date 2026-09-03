# -*- coding: utf-8 -*-
"""宠物主窗口：组装各 Mixin，管理窗口生命周期、事件分发与绘制编排。

功能拆分到各 Mixin：
- AnimationMixin: 呼吸 / 头部跟随 / 互动动画
- WalkMixin: 自动走动
- InputFollowMixin: 输入光标跟随
- KeyboardMixin: 键盘互动（脚掌拍键）
- MenuMixin: 右键菜单与开关
"""
import random
import time

from PySide6.QtCore import Qt, QPoint, QRect, QRectF, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from . import bubble, config, quotes, settings, sprite
from .animation_mixin import AnimationMixin
from .walk_mixin import WalkMixin
from .input_follow_mixin import InputFollowMixin
from .keyboard_mixin import KeyboardMixin
from .menu_mixin import MenuMixin


class Pet(MenuMixin, KeyboardMixin, InputFollowMixin, WalkMixin, AnimationMixin, QWidget):
    def __init__(self, persist=True):
        """persist=False 时不读写 QSettings，一律使用默认偏好（供测试使用）。"""
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)   # 重新显示时不抢占焦点
        self.setMouseTracking(True)   # 无按键悬停也接收 mouseMove，用于头部跟随

        self.persist = persist
        saved_flags, saved_scale, saved_input_scale = (
            settings.load() if persist
            else (dict(settings.DEFAULTS), settings.DEFAULT_SCALE,
                  config.INPUT_SCALE_DEFAULT))
        self._saved_flags = saved_flags

        self.src = QPixmap(config.resource_path("cat_soft.png"))   # 高清羽化素材
        self.scale = saved_scale
        self.kb_enabled = saved_flags["keyboard"]  # 键盘互动开关（影响底部键盘区留白）
        self.input_follow_enabled = saved_flags["input_follow"]
        self.input_follow_scale = saved_input_scale   # 跟随时的绝对缩放档位
        self.dragging = False
        self.drag_offset = QPoint()
        self._press_pos = None

        self._init_animation()

        layers = sprite.build_layers(self.src)
        self.body_src = layers.body
        self.head_src = layers.head
        self.head_x_frac = layers.head_x_frac
        self.head_h_frac = layers.head_h_frac
        self.paw_srcs = layers.paw_srcs
        self.paw_fracs = layers.paw_fracs
        self._rebuild_pixmap()

        scr = QApplication.primaryScreen().availableGeometry()
        self.screen_rect = scr
        self._apply_geometry(scr.center().x(), scr.bottom() + 1)

        self.bubble = bubble.Bubble()
        self.last_quote = None    # 上一条语录，随机时避免连续重复

        self._init_menu()
        self._init_input_follow()
        self._init_keyboard()
        self._init_walk()

        # 闲置提醒：超时无互动自动弹语录；任何互动（含悬停）重置计时
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(self._idle_chatter)
        self._reset_idle_timer()

        # 偏好写盘去抖：滚轮缩放会连续改动，攒一段时间再落一次盘
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_settings)

        # 置顶 / 走动这两项要真正生效必须走各自的 setter，而 setter 依赖上面
        # 建好的定时器，所以放在 __init__ 末尾统一施加。
        if not saved_flags["topmost"]:
            self._set_topmost(False)
        if saved_flags["walk"]:
            self._set_walk(True)

    # ---------- 偏好持久化 ----------
    def _current_flags(self):
        return {"topmost": self.act_topmost.isChecked(),
                "walk": self.walk_enabled,
                "keyboard": self.kb_enabled,
                "input_follow": self.input_follow_enabled}

    def _persistable_scale(self):
        """输入跟随期间 self.scale 是临时缩小值，要存进入前的原始比例。"""
        if self.input_follow_active and self.input_saved_scale is not None:
            return self.input_saved_scale
        return self.scale

    def _schedule_save(self):
        if self.persist:
            self._save_timer.start(800)

    def save_settings(self):
        """立即写回偏好；退出时由 app.main 调用，也作为去抖定时器的槽。"""
        self._save_timer.stop()
        if self.persist:
            settings.save(self._current_flags(), self._persistable_scale(),
                          self.input_follow_scale)

    # ---------- 素材缩放与窗口几何 ----------
    def _rebuild_pixmap(self):
        hpx = round(config.BASE_H * self.scale)
        self.pix = self.src.scaledToHeight(hpx, Qt.SmoothTransformation)
        self.body_pix = self.body_src.scaledToHeight(hpx, Qt.SmoothTransformation)
        head_h = max(1, round(self.head_src.height() * hpx / self.src.height()))
        self.head_pix = self.head_src.scaledToHeight(head_h, Qt.SmoothTransformation)
        self.paw_pix = [
            ps.scaledToHeight(max(1, round(ps.height() * hpx / self.src.height())),
                              Qt.SmoothTransformation)
            for ps in self.paw_srcs]
        # 窗口内为动画预留的空间：头顶留跳跃高度，左右留抖动/压扁/转头的余量，
        # 底部留放小键盘的区域（键盘互动）
        self.top_pad = round(self.pix.height() * 0.32)
        self.side_pad = round(self.pix.width() * 0.15)
        self.bottom_pad = round(self.pix.height() * 0.12) if self.kb_enabled else 0

    def _apply_geometry(self, foot_x, foot_y):
        """按当前素材重设窗口尺寸，并保持脚底中心位于 (foot_x, foot_y)。"""
        w = self.pix.width() + 2 * self.side_pad
        h = self.pix.height() + self.top_pad + self.bottom_pad + 6
        self.resize(w, h)
        self.move(foot_x - w // 2, foot_y - h)

    def _rebuild_geometry(self):
        """按当前 scale 与留白重建素材和窗口尺寸，保持脚底中心不动。

        缩放、键盘区留白增减都会改变窗口尺寸，善后动作（收回走动目标、
        丢弃浮点脚底）是共通的，因此单独成一个方法。"""
        foot_x = self.x() + self.width() // 2
        foot_y = self.y() + self.height()
        self._rebuild_pixmap()
        self._apply_geometry(foot_x, foot_y)
        # 窗口尺寸变了：走动目标重新收进区域，浮点脚底下一帧从实际几何重建
        if self.walk_target is not None:
            fx, fy = self._clamp_foot(self.walk_target.x(), self.walk_target.y())
            self.walk_target = QPoint(fx, fy)
        self._walk_pos = None

    def _set_scale(self, new_scale):
        self.scale = new_scale
        self._rebuild_geometry()

    # ---------- 绘制 ----------
    def _cat_rect(self):
        """当前猫咪主体（未叠加动画形变）的窗口内矩形。"""
        return QRect((self.width() - self.pix.width()) // 2,
                     self.height() - self.bottom_pad - self.pix.height() - 3,
                     self.pix.width(), self.pix.height())

    def _layout(self, t=None):
        """当前帧猫咪整体的目标矩形（浮点，亚像素）：脚底锚定 + 动画/呼吸形变。"""
        dx, dy, sx, sy = self._anim_offsets()
        bx, by = self._breath_scales(time.monotonic() if t is None else t)
        tw = self.pix.width() * sx * bx
        th = self.pix.height() * sy * by
        x = (self.width() - tw) / 2 + dx
        y = self.height() - self.bottom_pad - th - 3 - dy
        return QRectF(x, y, tw, th)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.facing < 0:
            # 向左走：整幅画面绕窗口中线水平镜像；键盘 / 脚掌一并镜像，位置关系不变
            p.translate(self.width(), 0)
            p.scale(-1, 1)
        r = self._layout()
        p.drawPixmap(r, self.body_pix, QRectF(self.body_pix.rect()))
        # 头部层：绕颈部转轴旋转后叠回身体（0° 时逐像素还原原图）
        px = r.x() + r.width() * config.HEAD_PIVOT[0]
        py = r.y() + r.height() * config.HEAD_PIVOT[1]
        p.save()
        p.translate(px, py)
        p.rotate(self.head_angle * self.facing)   # 镜像坐标下取反，视觉上仍朝鼠标侧倾
        p.translate(-px, -py)
        head_rect = QRectF(r.x() + r.width() * self.head_x_frac, r.y(),
                           r.width() * (1 - self.head_x_frac),
                           r.height() * self.head_h_frac)
        p.drawPixmap(head_rect, self.head_pix, QRectF(self.head_pix.rect()))
        p.restore()
        # 脚已从身体抠出：键盘画在身体前，脚层最后叠回（敲键时压向键盘）
        press_px = 0.0
        if self.kb_enabled:
            press_px = self._draw_keyboard(p) * config.PAW_PRESS_FRAC
        self._draw_paws(p, r, press_px)

    # ---------- 互动事件 ----------
    def mousePressEvent(self, e):
        self._stop_input_follow()
        self._reset_idle_timer()
        if e.button() == Qt.LeftButton:
            self.dragging = True
            self._press_pos = e.globalPosition().toPoint()
            self.drag_offset = self._press_pos - self.pos()

    def mouseMoveEvent(self, e):
        self._reset_idle_timer()
        self.hover_pos = e.position().toPoint()
        if self.dragging:
            self.move(e.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.dragging = False
            # 拖拽可能把宠物拖去别的屏幕 / 区域外：丢弃旧目标，停留后按当前屏幕重选
            if self.walk_enabled:
                self.walk_target = None
                self._walk_pos = None
                self._restart_walk_pause()
            # 位移很小视为点击 → 弹气泡 + 轮流触发互动动画
            if self._press_pos is not None and \
               (e.globalPosition().toPoint() - self._press_pos).manhattanLength() < 6:
                self.say(self._pick_quote("click"))
                self.play_anim()
            self._press_pos = None

    def leaveEvent(self, _):
        self.hover_pos = None   # 头部由 _frame 平滑回正

    def contextMenuEvent(self, e):
        self._stop_input_follow()
        self._reset_idle_timer()
        self.menu.exec(e.globalPos())

    def focusOutEvent(self, e):
        self._stop_input_follow()
        super().focusOutEvent(e)

    # ---------- 滚轮缩放：脚底位置不动 ----------
    def wheelEvent(self, e):
        self._stop_input_follow()
        self._reset_idle_timer()
        dy = e.angleDelta().y()
        if dy == 0:   # 纯横向滚动（触控板/倾斜滚轮）不缩放
            return
        factor = config.ZOOM_STEP if dy > 0 else 1 / config.ZOOM_STEP
        new_scale = min(config.MAX_SCALE, max(config.MIN_SCALE, self.scale * factor))
        if abs(new_scale - self.scale) < 1e-4:
            return
        self._set_scale(new_scale)
        self._schedule_save()
        self.update()

    # ---------- 屏幕 / 气泡 / 语录 ----------
    def _current_screen_rect(self):
        """宠物当前所在屏幕的可用区域；拖到副屏后气泡应按副屏定位。"""
        scr = self.screen() or QApplication.primaryScreen()
        return scr.availableGeometry()

    def say(self, text):
        self.screen_rect = self._current_screen_rect()
        head_y = self.y() + self.height() - self.bottom_pad - self.pix.height()   # 猫头顶
        anchor_x = self.x() + self.width() // 2
        # 窗口顶部距屏幕顶部太近时改到下方（用窗口位置而非猫头顶，
        # 因为 top_pad 留白会让猫头顶始终距屏幕顶有 ~89px，导致贴顶时阈值不触发）
        above = self.y() - 80 > self.screen_rect.top()
        anchor_y = head_y - 6 if above else self.y() + self.height() + 6
        self.bubble.popup(text, anchor_x, anchor_y, above, self.screen_rect)

    def wake_up(self):
        """另一实例试图启动时被唤醒：确保可见并打个招呼。"""
        self._stop_input_follow()
        self.show()
        self.raise_()
        self.say("我已经在这里啦，别再开一只喵~")
        self._reset_idle_timer()

    def _pick_quote(self, context="idle"):
        """按情境（click / idle）与当前时段随机选一条语录，避免与上一条重复。"""
        q = quotes.pick(context, self.last_quote)
        self.last_quote = q
        return q

    def _reset_idle_timer(self):
        """互动后重新计时；下次闲置提醒的间隔在区间内随机取值。"""
        self.idle_timer.start(random.randint(config.IDLE_MIN_MS, config.IDLE_MAX_MS))

    def _idle_chatter(self):
        """闲置到时：弹一条随机语录（拖拽中跳过），并继续计时等下一次。"""
        if not self.dragging:
            self.say(self._pick_quote("idle"))
        self._reset_idle_timer()
