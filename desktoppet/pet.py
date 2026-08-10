# -*- coding: utf-8 -*-
"""宠物主窗口：呼吸 / 头部跟随 / 互动动画 / 自动走动 / 键盘互动 / 输入跟随。"""
import math
import random
import time

from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QRectF
from PySide6.QtGui import QPainter, QColor, QPixmap
from PySide6.QtWidgets import QApplication, QWidget, QMenu

from . import bubble, config, input_follow, keyboard, placement, settings, sprite, winapi
from . import ime
from . import APP_VERSION


class Pet(QWidget):
    def __init__(self, persist=True):
        """persist=False 时不读写 QSettings，一律使用默认偏好（供测试使用）。"""
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)   # 重新显示时不抢占焦点
        self.setMouseTracking(True)   # 无按键悬停也接收 mouseMove，用于头部跟随

        self.persist = persist
        saved_flags, saved_scale = (settings.load() if persist
                                    else (dict(settings.DEFAULTS),
                                          settings.DEFAULT_SCALE))

        self.src = QPixmap(config.resource_path("cat_soft.png"))   # 高清羽化素材
        self.scale = saved_scale
        self.kb_enabled = saved_flags["keyboard"]  # 键盘互动开关（影响底部键盘区留白）
        self.input_follow_enabled = saved_flags["input_follow"]
        self.dragging = False
        self.drag_offset = QPoint()
        self._press_pos = None

        # 互动动画状态
        self.anim_kind = None
        self.anim_t = 0.0
        self.anim_index = 0
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(config.ANIM_TICK_MS)
        self.anim_timer.timeout.connect(self._anim_tick)

        # 呼吸 / 头部跟随状态
        self.reduced_motion = winapi.query_reduced_motion()
        self.t0 = time.monotonic()
        self.head_angle = 0.0     # 当前头部角度（度，正值向右倾）
        self.head_target = 0.0
        self.hover_pos = None     # 悬停时的窗口内坐标；None 表示不在窗口内

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

        self.menu = QMenu()
        version_item = self.menu.addAction("DesktopPet %s" % APP_VERSION)
        version_item.setEnabled(False)      # 只作标题展示，不可点击
        self.menu.addSeparator()
        self.act_topmost = self.menu.addAction("始终置顶")
        self.act_topmost.setCheckable(True)
        self.act_topmost.setChecked(saved_flags["topmost"])
        self.act_topmost.toggled.connect(self._set_topmost)
        self.act_walk = self.menu.addAction("自动走动")
        self.act_walk.setCheckable(True)
        self.act_walk.setChecked(saved_flags["walk"])
        self.act_walk.toggled.connect(self._set_walk)
        self.act_kb = self.menu.addAction("键盘互动")
        self.act_kb.setCheckable(True)
        self.act_kb.setChecked(saved_flags["keyboard"])
        self.act_kb.toggled.connect(self._set_kb)
        self.act_input = self.menu.addAction("输入跟随")
        self.act_input.setCheckable(True)
        self.act_input.setChecked(saved_flags["input_follow"])
        self.act_input.toggled.connect(self._set_input_follow)
        self.menu.addSeparator()
        self.menu.addAction("退出", QApplication.quit)

        # 输入跟随：保存进入前的缩放 / 脚底位置，短周期刷新跨进程光标。
        self.input_follow_active = False
        self.input_saved_scale = None
        self.input_saved_foot = None
        self.input_idle_timer = QTimer(self)
        self.input_idle_timer.setSingleShot(True)
        self.input_idle_timer.timeout.connect(self._stop_input_follow)
        self.input_poll_timer = QTimer(self)
        self.input_poll_timer.setInterval(config.INPUT_POLL_MS)
        self.input_poll_timer.timeout.connect(self._input_follow_tick)

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

        # 自动走动状态：目标点为脚底中心的屏幕坐标，None 表示正在停留；
        # _walk_pos 为浮点脚底位置（避免逐帧取整累计出速度/方向量化误差）
        self.walk_enabled = False
        self.walk_target = None
        self._walk_pos = None
        self.walk_timer = QTimer(self)
        self.walk_timer.setInterval(config.WALK_TICK_MS)
        self.walk_timer.timeout.connect(self._walk_tick)
        self.walk_pause_timer = QTimer(self)
        self.walk_pause_timer.setSingleShot(True)
        self.walk_pause_timer.timeout.connect(self._on_walk_pause_done)

        # 闲置提醒：超时无互动自动弹语录；任何互动（含悬停）重置计时
        self.idle_timer = QTimer(self)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(self._idle_chatter)
        self._reset_idle_timer()

        # 动画帧驱动（呼吸 + 头部角度平滑）；减少动态效果时自动静默
        self.frame_timer = QTimer(self)
        self.frame_timer.timeout.connect(self._frame)
        self.frame_timer.start(config.FRAME_MS)

        # 定期复查系统"减少动态效果"开关，随系统设置即时降级 / 恢复
        self.rm_timer = QTimer(self)
        self.rm_timer.timeout.connect(self._poll_reduced_motion)
        self.rm_timer.start(4000)

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
            settings.save(self._current_flags(), self._persistable_scale())

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

    # ---------- 置顶开关 ----------
    def _set_topmost(self, on):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        # 气泡置顶状态随宠物同步，避免宠物被遮住时气泡还单独浮在最上层
        bubble_visible = self.bubble.isVisible()
        self.bubble.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        if bubble_visible:
            self.bubble.show()
        # 修改窗口标志会隐藏并重建原生窗口；延后到菜单的嵌套事件循环结束后
        # 再重新显示，配合 WA_ShowWithoutActivating 避免闪烁 / 抢占前台焦点
        QTimer.singleShot(0, self.show)
        self._schedule_save()

    # ---------- 自动走动 ----------
    def _walk_region(self):
        """走动限定区域：宠物当前所在屏幕可用区域的右下 1/4。"""
        scr = self._current_screen_rect()
        return QRect(scr.center(), scr.bottomRight())

    def _foot_bounds(self):
        """脚底中心点在走动区域内的合法区间 (lo_x, hi_x, lo_y, hi_y)：
        向内收缩半个窗口宽 / 整个窗口高，保证窗口整体不越出区域。"""
        r = self._walk_region()
        lo_x, hi_x = r.left() + self.width() // 2, r.right() - self.width() // 2
        lo_y, hi_y = r.top() + self.height(), r.bottom()
        if lo_x > hi_x:     # 区域比窗口还窄 / 矮时退化为贴中线 / 贴底
            lo_x = hi_x = r.center().x()   # （此时窗口不可避免会伸出区域）
        if lo_y > hi_y:
            lo_y = hi_y = r.bottom()
        return lo_x, hi_x, lo_y, hi_y

    def _clamp_foot(self, fx, fy):
        """把脚底中心点收进走动区域的合法区间。"""
        lo_x, hi_x, lo_y, hi_y = self._foot_bounds()
        return max(lo_x, min(fx, hi_x)), max(lo_y, min(fy, hi_y))

    def _walk_paused(self):
        """走动的临时暂停条件：拖拽 / 右键菜单打开 / 气泡显示中 / 减少动态效果。"""
        return (self.dragging or self.reduced_motion or self.input_follow_active
                or self.menu.isVisible() or self.bubble.isVisible())

    def _pick_walk_target(self):
        """在合法区间内均匀随机选下一个脚底目标点（不经 clamp，避免边缘聚集）。"""
        lo_x, hi_x, lo_y, hi_y = self._foot_bounds()
        self.walk_target = QPoint(random.randint(lo_x, hi_x),
                                  random.randint(lo_y, hi_y))
        self._walk_pos = None   # 下一 tick 从当前窗口位置重新起步

    def _on_walk_pause_done(self):
        """停留结束：若正处于暂停态则不选新目标（相当于冻结停留），
        恢复后由 _walk_tick 兜底重新计时。"""
        if self.walk_enabled and not self._walk_paused():
            self._pick_walk_target()

    def _set_walk(self, on):
        self.walk_enabled = on
        if on:
            self._pick_walk_target()
            self.walk_timer.start()
        else:
            self.walk_timer.stop()
            self.walk_pause_timer.stop()
            self.walk_target = None
            self._walk_pos = None
        self._schedule_save()

    def _restart_walk_pause(self):
        self.walk_pause_timer.start(
            random.randint(config.WALK_PAUSE_MIN_MS, config.WALK_PAUSE_MAX_MS))

    def _walk_tick(self):
        """每帧向目标匀速走一步；浮点累计位置，move 时才取整。"""
        if self._walk_paused():
            return
        if self.walk_target is None:
            # 停留计时被暂停冻结 / 外部打断后兜底重新排期
            if not self.walk_pause_timer.isActive():
                self._restart_walk_pause()
            return
        if self._walk_pos is None:
            self._walk_pos = (float(self.x() + self.width() // 2),
                              float(self.y() + self.height()))
        fx, fy = self._walk_pos
        dx = self.walk_target.x() - fx
        dy = self.walk_target.y() - fy
        dist = math.hypot(dx, dy)
        step = config.WALK_SPEED * config.WALK_TICK_MS / 1000.0
        if dist <= step:    # 到达：吸附到目标点并停留一会儿
            nx, ny = self.walk_target.x(), self.walk_target.y()
            self.walk_target = None
            self._walk_pos = None
            self._restart_walk_pause()
        else:
            fx += dx / dist * step
            fy += dy / dist * step
            self._walk_pos = (fx, fy)
            nx, ny = round(fx), round(fy)
        self.move(nx - self.width() // 2, ny - self.height())

    # ---------- 呼吸 / 头部跟随 ----------
    def _breath_scales(self, t):
        """呼吸缩放系数 (宽, 高)：纵向正弦起伏、横向轻微反相；减少动态效果时恒 1。"""
        if self.reduced_motion:
            return 1.0, 1.0
        ph = math.sin(2 * math.pi * (t - self.t0) / config.BREATH_PERIOD)
        return 1.0 - config.BREATH_AMP_X * ph, 1.0 + config.BREATH_AMP_Y * ph

    def _cat_rect(self):
        """当前猫咪主体（未叠加动画形变）的窗口内矩形。"""
        return QRect((self.width() - self.pix.width()) // 2,
                     self.height() - self.bottom_pad - self.pix.height() - 3,
                     self.pix.width(), self.pix.height())

    def _update_head_target(self):
        """按鼠标相对颈部转轴的方位更新头部目标角；不悬停 / 拖拽 / 降级时回正。"""
        if (self.reduced_motion or self.dragging or self.hover_pos is None
                or not self._cat_rect().contains(self.hover_pos)):
            self.head_target = 0.0
            return
        r = self._cat_rect()
        px = r.x() + r.width() * config.HEAD_PIVOT[0]
        py = r.y() + r.height() * config.HEAD_PIVOT[1]
        dx = self.hover_pos.x() - px
        dy = self.hover_pos.y() - py
        ang = math.degrees(math.atan2(dx, max(8.0, -dy))) * config.HEAD_GAIN
        self.head_target = max(-config.HEAD_MAX_DEG, min(config.HEAD_MAX_DEG, ang))

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
        k = 1.0 - math.exp(-config.FRAME_MS / 1000.0 / config.HEAD_TAU)
        self.head_angle += (self.head_target - self.head_angle) * k
        if abs(self.head_angle - self.head_target) < 0.02:
            self.head_angle = self.head_target
        self.update()

    def _poll_reduced_motion(self):
        rm = winapi.query_reduced_motion()
        if rm != self.reduced_motion:
            self.reduced_motion = rm
            if rm:
                self.head_target = 0.0
                self.head_angle = 0.0
                self.anim_kind = None
                self.anim_timer.stop()
                self._stop_input_follow()   # 跟随属于动效，一并退出并还原
            else:
                self.t0 = time.monotonic()   # 呼吸从静止相位平滑起步
            self.update()

    # ---------- 互动动画 ----------
    def play_anim(self):
        """点击时轮流触发：跳跃 → 压扁回弹 → 左右抖动；减少动态效果时跳过。"""
        if self.reduced_motion:
            return
        self.anim_kind = config.ANIM_KINDS[self.anim_index % len(config.ANIM_KINDS)]
        self.anim_index += 1
        self.anim_t = 0.0
        self.anim_timer.start()

    def _anim_tick(self):
        self.anim_t += config.ANIM_TICK_MS / config.ANIM_DUR[self.anim_kind]
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

    # ---------- 输入光标跟随 ----------
    def _move_to_input_context(self, context):
        pos = placement.safe_position(context.caret, context.focus,
                                      context.candidate, self.size(),
                                      context.screen)
        self.move(pos)

    def _set_input_follow(self, on):
        """开关输入跟随；关闭时立刻退出跟随并还原位置与缩放。"""
        self.input_follow_enabled = on
        if not on:
            self._stop_input_follow()
        self._schedule_save()

    def _input_follow_allowed(self):
        """输入跟随会让宠物在屏幕上大幅跳动，是最显眼的一种动效，
        因此与呼吸 / 转头 / 走动一样服从系统"减少动态效果"。"""
        return self.input_follow_enabled and not self.reduced_motion

    def _input_on_key(self):
        """Enter or refresh input-follow mode when the foreground exposes a caret."""
        if not self._input_follow_allowed():
            return
        if self.input_follow_active:
            # 已在跟随中：位置由 input_poll_timer 按 config.INPUT_POLL_MS 刷新，
            # 这里只需为按键续期空闲计时。跨进程查询很贵，不必每键重跑一次。
            self.input_idle_timer.start(config.INPUT_IDLE_MS)
            return
        context = input_follow.query_input_context()
        if context is None:
            return
        self.input_saved_scale = self.scale
        self.input_saved_foot = QPoint(
            self.x() + self.width() // 2, self.y() + self.height())
        self.input_follow_active = True
        self._set_scale(self.input_saved_scale * config.INPUT_SCALE_FACTOR)
        self.input_poll_timer.start()
        self._move_to_input_context(context)
        self.input_idle_timer.start(config.INPUT_IDLE_MS)

    def _input_follow_tick(self):
        """Refresh after the target application has processed the latest key."""
        if not self.input_follow_active:
            return
        context = input_follow.query_input_context()
        if context is not None:
            self._move_to_input_context(context)

    def _stop_input_follow(self):
        """Leave input mode and restore the exact pre-input scale and foot anchor."""
        self.input_idle_timer.stop()
        self.input_poll_timer.stop()
        ime.reset_cache()   # 下次进入输入跟随时重新探测，不沿用旧结论
        if not self.input_follow_active:
            return
        saved_scale = self.input_saved_scale
        saved_foot = QPoint(self.input_saved_foot)
        self.input_follow_active = False
        self.input_saved_scale = None
        self.input_saved_foot = None
        self._set_scale(saved_scale)
        self._apply_geometry(saved_foot.x(), saved_foot.y())
        self.update()

    # ---------- 键盘互动 ----------
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

    # ---------- 绘制 ----------
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
        r = self._layout()
        p.drawPixmap(r, self.body_pix, QRectF(self.body_pix.rect()))
        # 头部层：绕颈部转轴旋转后叠回身体（0° 时逐像素还原原图）
        px = r.x() + r.width() * config.HEAD_PIVOT[0]
        py = r.y() + r.height() * config.HEAD_PIVOT[1]
        p.save()
        p.translate(px, py)
        p.rotate(self.head_angle)
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

    # ---------- 互动 ----------
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
                self.say(self._pick_quote())
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

    # ---------- 语录 / 闲置提醒 ----------
    def _pick_quote(self):
        """随机选一条语录，避免与上一条重复。"""
        q = random.choice([x for x in config.QUOTES if x != self.last_quote] or config.QUOTES)
        self.last_quote = q
        return q

    def _reset_idle_timer(self):
        """互动后重新计时；下次闲置提醒的间隔在区间内随机取值。"""
        self.idle_timer.start(random.randint(config.IDLE_MIN_MS, config.IDLE_MAX_MS))

    def _idle_chatter(self):
        """闲置到时：弹一条随机语录（拖拽中跳过），并继续计时等下一次。"""
        if not self.dragging:
            self.say(self._pick_quote())
        self._reset_idle_timer()

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
