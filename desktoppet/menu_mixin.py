# -*- coding: utf-8 -*-
"""右键菜单 Mixin：构建宠物右键菜单并处理各开关的切换。

菜单状态与 QSettings 持久化联动；开机自启动项与注册表实时对账。"""
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QActionGroup, QDesktopServices
from PySide6.QtWidgets import QMenu, QApplication

from . import autostart, config, probe, quotes
from . import APP_VERSION


class MenuMixin:
    """右键菜单构建与开关回调。

    依赖宿主提供：self.persist、self._saved_flags、self.kb_enabled、
    self.input_follow_enabled、self.input_follow_scale、self.bubble、
    self._schedule_save()、self.show()、self.setWindowFlag()。
    _init_menu 须在 self.bubble 创建之后调用。"""

    def _init_menu(self):
        self.menu = QMenu()
        version_item = self.menu.addAction("DesktopPet %s" % APP_VERSION)
        version_item.setEnabled(False)      # 只作标题展示，不可点击
        self.menu.addSeparator()

        self.act_topmost = self.menu.addAction("始终置顶")
        self.act_topmost.setCheckable(True)
        self.act_topmost.setChecked(self._saved_flags["topmost"])
        self.act_topmost.toggled.connect(self._set_topmost)

        self.act_walk = self.menu.addAction("自动走动")
        self.act_walk.setCheckable(True)
        self.act_walk.setChecked(self._saved_flags["walk"])
        self.act_walk.toggled.connect(self._set_walk)

        self.act_kb = self.menu.addAction("键盘互动")
        self.act_kb.setCheckable(True)
        self.act_kb.setChecked(self.kb_enabled)
        self.act_kb.toggled.connect(self._set_kb)

        self.act_input = self.menu.addAction("输入跟随")
        self.act_input.setCheckable(True)
        self.act_input.setChecked(self.input_follow_enabled)
        self.act_input.toggled.connect(self._set_input_follow)

        # 跟随大小档位：始终可用——档位是独立的存储偏好，可以先设好再开跟随。
        # 显式指定父对象后由 C++ 侧持有；若用 addMenu("标题") 让 PySide6 把所有权
        # 交给 Python，别处读一次 QAction.menu() 产生的临时包装被回收时会连带
        # 析构掉这个子菜单，self.follow_scale_menu 随即失效。
        self.follow_scale_menu = QMenu("输入跟随大小", self.menu)
        self.menu.addMenu(self.follow_scale_menu)
        self.follow_scale_group = QActionGroup(self)
        self.follow_scale_group.setExclusive(True)
        self.follow_scale_actions = {}
        for choice in config.INPUT_SCALE_CHOICES:
            action = self.follow_scale_menu.addAction("%d%%" % round(choice * 100))
            action.setCheckable(True)
            action.setActionGroup(self.follow_scale_group)
            action.setChecked(abs(choice - self.input_follow_scale) < 1e-9)
            self.follow_scale_actions[choice] = action
            # 只在选中时响应，否则同一次切换会连带触发被取消项的信号
            action.triggered.connect(
                lambda checked, value=choice: checked and
                self._set_input_follow_scale(value))

        self.act_autostart = self.menu.addAction("开机自动启动")
        self.act_autostart.setCheckable(True)
        # persist=False（测试）不碰真实注册表；弹菜单前再与注册表对账，
        # 因为启动项也可能被任务管理器等外部工具改动
        self.act_autostart.setChecked(self.persist and autostart.is_enabled())
        self.act_autostart.toggled.connect(self._set_autostart)
        if self.persist:
            self.menu.aboutToShow.connect(self._sync_autostart)

        self.menu.addSeparator()
        self.menu.addAction("编辑语录…", self._edit_quotes)
        self.menu.addAction("复制输入跟随诊断", self._copy_probe_report)
        self.menu.addSeparator()
        self.menu.addAction("退出", QApplication.quit)

    # ---------- 语录文件 ----------
    def _edit_quotes(self):
        """确保用户语录文件存在（首次从内置复制），再用系统默认程序打开。"""
        path = quotes.ensure_user_file()
        if path is None:
            self.say("语录文件创建失败了喵……")
            return
        if self.persist:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        self.say("改完保存后我就会说新话啦~")

    # ---------- 输入跟随诊断 ----------
    def _copy_probe_report(self):
        QApplication.clipboard().setText(probe.report())
        self.say("诊断信息已复制到剪贴板~")

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

    # ---------- 开机自动启动 ----------
    def _set_autostart(self, on):
        """写注册表 Run 项。状态存在注册表里，不进 QSettings，无需 _schedule_save。"""
        if not self.persist:
            return    # 测试模式不碰真实注册表
        if not autostart.set_enabled(on):
            # 写失败（如注册表被策略锁定）：回退勾选，不能显示已开启却无效
            self.act_autostart.blockSignals(True)
            self.act_autostart.setChecked(not on)
            self.act_autostart.blockSignals(False)

    def _sync_autostart(self):
        """弹菜单前与注册表对账：启动项可能被任务管理器等外部工具改动。"""
        self.act_autostart.blockSignals(True)
        self.act_autostart.setChecked(autostart.is_enabled())
        self.act_autostart.blockSignals(False)
