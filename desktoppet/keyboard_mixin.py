# -*- coding: utf-8 -*-
"""键盘互动 Mixin：全局键盘钩子驱动两只前脚拍打身前小键盘。

按 QWERTY 左右分区选脚，未知键交替；系统自动重复忽略。"""
import time

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor

from . import keyboard


class KeyboardMixin:
    """键盘互动的状态、钩子回调与绘制。

    依赖宿主提供：self.kb_enabled、self.reduced_motion、self.pix、self.bottom_pad、
    self.width()、self.height()、self.paw_pix、self.paw_fracs、self.update()、
    self._rebuild_geometry()、self._schedule_save()、self._input_on_key()、
    self.act_kb。"""

    def _init_keyboard(self):
        # 键盘互动：全局钩子监听敲键，两只脚拍打身前小键盘。
        # _held 记录按住中的物理键标识 → 所用脚（忽略系统自动重复、松键配对）；
        # _paw_held[i] 为该脚当前按住的键数，>0 时脚保持压下；
        # _paw_lift[i] 为该脚开始抬起的时刻（保证快速敲击也有可见的按压段）
        self._held = {}
        self._paw_held = [0, 0]
        self._paw_lift = [-1e9, -1e9]
        self._paw_alt = 0            # 未知分区按键交替用脚
        self.key_listener = keyboard.KeyListener()
        self.key_listener.pressed.connect(self._on_global_key)
        self.key_listener.released.connect(self._on_global_key_up)
        self.key_listener.failed.connect(self._on_kb_hook_failed)
        self.key_listener.start()    # 信号连好后再启动，避免漏掉 failed 通知

    def _set_kb(self, on):
        """开关键盘互动：底部键盘区留白联动增减，脚底位置保持不动。"""
        self.kb_enabled = on
        self._held.clear()
        self._paw_held = [0, 0]
        self._paw_lift = [-1e9, -1e9]
        self._rebuild_geometry()
        self._schedule_save()
        self.update()

    def _on_kb_hook_failed(self):
        """全局钩子安装失败：关闭并禁用键盘互动，避免菜单显示已开启却无效。"""
        self.act_kb.setChecked(False)
        self.act_kb.setEnabled(False)
        self.act_kb.setText("键盘互动（不可用）")

    def _on_global_key(self, vk, key_id):
        """物理按键按下：按 QWERTY 左右分区选脚，未知键交替；自动重复忽略。"""
        self._input_on_key()
        if not self.kb_enabled or self.reduced_motion or key_id in self._held:
            return
        if vk in keyboard.LEFT_VKS:
            side = 0
        elif vk in keyboard.RIGHT_VKS:
            side = 1
        else:
            self._paw_alt ^= 1
            side = self._paw_alt
        self._held[key_id] = side
        self._paw_held[side] += 1
        # 抬起时刻至少在按下后 keyboard.KB_TAP_HOLD_MS，快速敲击也有可见按压段
        self._paw_lift[side] = time.monotonic() + keyboard.KB_TAP_HOLD_MS / 1000.0
        self.update()

    def _on_global_key_up(self, vk, key_id):
        """物理按键松开：对应脚的按住计数 -1，归零后从抬起时刻开始回弹。"""
        side = self._held.pop(key_id, None)
        if side is None:    # 启动前就按住的键 / 开关切换期间的松键
            return
        self._paw_held[side] -= 1
        if self._paw_held[side] <= 0:
            self._paw_held[side] = 0
            self._paw_lift[side] = max(self._paw_lift[side], time.monotonic())
            self.update()

    def _paw_progress(self, side, now):
        """脚掌按压进度（0 悬停 ~ 1 压在键上）：按住保持压下，松开平滑抬回。"""
        if self._paw_held[side] > 0 or now < self._paw_lift[side]:
            return 1.0
        dt = (now - self._paw_lift[side]) * 1000.0
        if dt < keyboard.KB_TAP_LIFT_MS:
            u = dt / keyboard.KB_TAP_LIFT_MS
            return 1.0 - u * u * (3 - 2 * u)   # smoothstep 抬起
        return 0.0

    def _draw_keyboard(self, p):
        """画身前小键盘（固定在地面，不随互动动画位移）；返回键盘高度。"""
        kw = self.pix.width() * 0.62
        kh = self.bottom_pad * 1.35
        kx = (self.width() - kw) / 2
        ky = self.height() - 2 - kh
        kb = QRectF(kx, ky, kw, kh)

        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(45, 47, 56))
        p.setBrush(QColor(70, 72, 82))
        p.drawRoundedRect(kb, kh * 0.18, kh * 0.18)
        # 键帽：3 行小圆角矩形，行间留缝
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(168, 171, 184))
        rows, gap = 3, kh * 0.09
        key_h = (kh - gap * (rows + 1)) / rows
        for r_i in range(rows):
            y = ky + gap + r_i * (key_h + gap)
            n = 10 - r_i          # 下面的行键少一点，略有键盘感
            key_w = (kw - gap * (n + 1)) / n
            for c in range(n):
                x = kx + gap + c * (key_w + gap)
                p.drawRoundedRect(QRectF(x, y, key_w, key_h),
                                  key_h * 0.25, key_h * 0.25)
        return kh

    def _draw_paws(self, p, r, press_px):
        """把从原图裁出的两只脚原位叠回（静止时与身体逐像素重合）；
        敲键时顶端固定、向下拉伸 press_px 像素压到键盘上。"""
        now = time.monotonic()
        for side, (pix, (xf, yf, wf, hf)) in enumerate(
                zip(self.paw_pix, self.paw_fracs)):
            prog = self._paw_progress(side, now)
            rect = QRectF(r.x() + r.width() * xf,
                          r.y() + r.height() * yf,
                          r.width() * wf,
                          r.height() * hf + press_px * prog)
            p.drawPixmap(rect, pix, QRectF(pix.rect()))
