# 输入光标跟随功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在所有前台文本控件输入时，让宠物跟随插入光标、缩小到进入前缩放值的 20%，避开输入控件和 IME 候选区域，并在输入结束后恢复原位置和缩放。

**Architecture:** 保持单文件 PySide6 应用。`pet_v2.py` 新增 ctypes Win32 光标/IME 查询、纯 QRect 几何定位函数和 Pet 输入跟随状态机；现有全局键盘钩子作为触发源，50ms 轮询补偿目标应用更新延迟。`selftest_v2.py` 覆盖几何、状态和异常降级，README 更新功能说明。

**Tech Stack:** Python 3.12、PySide6 6.11、Windows user32/imm32 ctypes API、现有 PyInstaller spec。

## Global Constraints

- 复用现有 Windows 全局低阶键盘钩子，不新增第三方 Python 依赖。
- 输入结束判定固定为 1000ms 无按键。
- 临时缩放为进入输入状态前 `scale * 0.2`，允许低于滚轮最小值 `0.25`。
- 输入跟随不受“键盘互动”或“减少动态效果”开关影响。
- 点击、拖拽、滚轮或焦点丢失结束跟随，并恢复进入前缩放和脚底位置。
- 所有脚本命令使用 PowerShell，脚本首行 `$ErrorActionPreference = 'Stop'`；文件读写指定 UTF8。

---

### Task 1: 添加几何与状态测试

**Files:**
- Modify: `selftest_v2.py`（顶部 Qt 导入及新增输入跟随测试区段）

**Interfaces:**
- Consumes: 计划后续实现的 `pet_v2._input_safe_position(caret, focus, candidate, pet_size, screen, gap=12)`。
- Produces: 明确的 QRect/QPoint 几何契约和 Pet 输入状态断言。

- [ ] **Step 1: 写失败的几何测试**

在现有 Qt 导入中加入 `QSize`，并新增以下断言区段（放在缩放回归前）：

```python
from PySide6.QtCore import QSize

screen = QRect(0, 0, 1280, 720)
caret = QRect(500, 300, 2, 20)
focus = QRect(450, 280, 220, 45)
candidate = QRect(470, 325, 280, 80)
pos = m._input_safe_position(caret, focus, candidate, QSize(60, 52), screen)
pet_rect = QRect(pos, QSize(60, 52))
assert pet_rect.top() >= candidate.bottom() + 13
assert not pet_rect.intersects(focus)
assert not pet_rect.intersects(candidate)
assert screen.contains(pet_rect)

edge = m._input_safe_position(QRect(1268, 690, 2, 20), QRect(1200, 680, 79, 39), None,
                              QSize(60, 52), screen)
assert screen.contains(QRect(edge, QSize(60, 52)))
```

- [ ] **Step 2: 运行测试确认失败**

运行：`$ErrorActionPreference = 'Stop'; $env:QT_QPA_PLATFORM = 'offscreen'; python selftest_v2.py`

预期：因 `pet_v2._input_safe_position` 尚不存在而失败。

- [ ] **Step 3: 写失败的状态测试**

在创建 `p = m.Pet()` 后加入可控查询替身和状态断言：

```python
old_query = m.query_input_context
saved_scale = p.scale
saved_foot = (p.x() + p.width() // 2, p.y() + p.height())
m.query_input_context = lambda: m.InputContext(
    QRect(300, 200, 2, 20), QRect(250, 180, 140, 45), None,
    QRect(0, 0, 1280, 720))
p._input_on_key()
assert p.input_follow_active and abs(p.scale - saved_scale * 0.2) < 1e-9
active_scale = p.scale
p._input_on_key()
assert p.input_saved_scale == saved_scale and p.scale == active_scale
p._stop_input_follow()
assert not p.input_follow_active and abs(p.scale - saved_scale) < 1e-9
assert (p.x() + p.width() // 2, p.y() + p.height()) == saved_foot
m.query_input_context = old_query
```

- [ ] **Step 4: 运行测试确认状态测试失败**

运行同 Step 2。预期：因 `InputContext`、`query_input_context` 和输入状态方法尚不存在而失败。

- [ ] **Step 5: 提交测试基线**

```powershell
$ErrorActionPreference = 'Stop'
& 'C:\Program Files\Git\bin\git.exe' add -- selftest_v2.py
& 'C:\Program Files\Git\bin\git.exe' commit -m '测试输入光标跟随几何与状态'
```

### Task 2: 实现 Win32 光标和 IME 查询

**Files:**
- Modify: `pet_v2.py`（Win32 结构体、常量和查询函数，约在 `KeyListener` 前）

**Interfaces:**
- Consumes: Windows foreground thread and caret APIs.
- Produces: `InputContext` named tuple和 `query_input_context() -> InputContext | None`。

- [ ] **Step 1: 定义 ctypes 数据结构和常量**

加入 `namedtuple` 导入，以及 `RECT`、`POINT`、`GUITHREADINFO`、`CANDIDATEFORM` 结构；设置 `user32.GetForegroundWindow`、`GetWindowThreadProcessId`、`GetGUIThreadInfo`、`ClientToScreen`、`GetWindowRect` 和 `IsWindow` 的 `argtypes/restype`。定义 `INPUT_IDLE_MS = 1000`、`INPUT_POLL_MS = 50`、`INPUT_SCALE_FACTOR = 0.2`、`INPUT_GAP = 12`。

- [ ] **Step 2: 实现屏幕坐标转换和候选区域查询**

实现 `_win_rect(hwnd)` 将有效 Win32 RECT 转成 `QRect`；实现 `_ime_candidate_rect(hwnd)`，调用 `imm32.ImmGetContext`、`ImmGetCandidateWindow`、`ImmReleaseContext`，只返回宽高均为正的区域，任意 API 异常返回 `None`。

- [ ] **Step 3: 实现 `query_input_context()`**

按以下流程返回 `InputContext(caret, focus, candidate, screen)`：前台句柄为空或非 Windows 返回 `None`；通过前台线程的 `GUITHREADINFO` 获取 `hwndCaret` 和 `rcCaret`；使用两个 `ClientToScreen` 调用转换 caret；focus 取 `hwndFocus or hwndCaret` 的窗口矩形；candidate 使用 `_ime_candidate_rect(hwndCaret)`；screen 使用 `QApplication.screenAt(caret.center())` 的 `availableGeometry()`，无匹配时回退主屏。查询失败只返回 `None`。

- [ ] **Step 4: 运行测试确认查询层通过**

运行：`$ErrorActionPreference = 'Stop'; $env:QT_QPA_PLATFORM = 'offscreen'; python selftest_v2.py`

预期：查询相关失败测试不抛异常；几何和状态测试仍因后续函数未实现而失败。

- [ ] **Step 5: 提交查询层**

```powershell
$ErrorActionPreference = 'Stop'
& 'C:\Program Files\Git\bin\git.exe' add -- pet_v2.py
& 'C:\Program Files\Git\bin\git.exe' commit -m '读取前台输入光标和 IME 候选区域'
```

### Task 3: 实现安全定位几何

**Files:**
- Modify: `pet_v2.py`（新增 `_input_safe_position`，放在 Pet 类前的纯函数区）
- Test: `selftest_v2.py`（运行 Task 1 几何用例）

**Interfaces:**
- Consumes: `QRect` caret/focus/candidate、`QSize` pet_size、`QRect` screen、`gap`。
- Produces: `QPoint` 窗口左上角；返回矩形始终在屏幕内，优先位于光标下方且不与避让矩形相交。

- [ ] **Step 1: 实现候选位置生成**

按顺序生成“光标下方、输入控件/候选区域底部下方、光标上方、光标左侧、光标右侧”的候选 `QRect`；所有候选水平坐标先按 caret 中心计算，再夹到 screen 内。

- [ ] **Step 2: 实现碰撞和边界判断**

将 focus/candidate 用 `adjusted(-gap, -gap, gap, gap)` 扩大；候选矩形必须 `screen.contains(rect)` 且不与任一扩大矩形 `intersects`。返回第一个满足条件的候选；若所有位置都无法满足，返回屏幕内的下方夹紧位置，保证函数始终有结果。

- [ ] **Step 3: 运行几何测试确认通过**

运行：`$ErrorActionPreference = 'Stop'; $env:QT_QPA_PLATFORM = 'offscreen'; python selftest_v2.py`

预期：Task 1 的几何断言通过，状态断言仍等待 Task 4。

- [ ] **Step 4: 提交几何层**

```powershell
$ErrorActionPreference = 'Stop'
& 'C:\Program Files\Git\bin\git.exe' add -- pet_v2.py selftest_v2.py
& 'C:\Program Files\Git\bin\git.exe' commit -m '计算输入光标跟随的安全位置'
```

### Task 4: 接入 Pet 输入跟随状态机

**Files:**
- Modify: `pet_v2.py`（`Pet.__init__`、全局按键入口、交互事件和新状态方法）
- Test: `selftest_v2.py`（运行 Task 1 状态用例）

**Interfaces:**
- Consumes: `query_input_context`, `_input_safe_position`, existing `_set_scale` / `_apply_geometry`。
- Produces: `Pet._input_on_key()`, `Pet._input_follow_tick()`, `Pet._stop_input_follow()`。

- [ ] **Step 1: 初始化状态和定时器**

在 `__init__` 中初始化 `input_follow_active = False`、`input_saved_scale = None`、`input_saved_foot = None`；创建单次 `input_idle_timer` 连接 `_stop_input_follow`，创建 `input_poll_timer` 连接 `_input_follow_tick`，间隔分别为 `INPUT_IDLE_MS` 和 `INPUT_POLL_MS`。

- [ ] **Step 2: 实现进入和刷新逻辑**

`_input_on_key()` 查询上下文；首次得到有效上下文时保存脚底和缩放，调用 `_set_scale(saved * INPUT_SCALE_FACTOR)`，启动轮询；每次都重启 idle timer。`_input_follow_tick()` 在激活状态下查询上下文，调用 `_input_safe_position`，按目标左上角移动；查询暂时失败时保持上一次位置。

- [ ] **Step 3: 实现完整退出和恢复**

`_stop_input_follow()` 停止两个定时器，若曾激活则保存待恢复值到局部变量，先 `_set_scale(saved_scale)`，再 `_apply_geometry(saved_foot_x, saved_foot_y)`，最后清空状态。重复调用必须幂等。

- [ ] **Step 4: 接入现有事件并暂停自动走动**

在 `_on_global_key` 最前调用 `_input_on_key()`；在 `mousePressEvent`、`wheelEvent`、`contextMenuEvent` 和拖拽开始处调用 `_stop_input_follow()`；让 `_walk_paused()` 将 `input_follow_active` 视为暂停条件。保留原有脚掌按键去重和动画逻辑。

- [ ] **Step 5: 运行状态与全量测试**

运行：`$ErrorActionPreference = 'Stop'; $env:QT_QPA_PLATFORM = 'offscreen'; python selftest_v2.py`

预期：输出 `ALL PASS`，并验证输入状态临时缩放、重复按键基准保持、退出恢复位置/缩放。

- [ ] **Step 6: 提交状态机**

```powershell
$ErrorActionPreference = 'Stop'
& 'C:\Program Files\Git\bin\git.exe' add -- pet_v2.py selftest_v2.py
& 'C:\Program Files\Git\bin\git.exe' commit -m '实现输入光标跟随与临时缩放'
```

### Task 5: 更新文档并执行验收

**Files:**
- Modify: `README.md`（功能清单和行为说明）

- [ ] **Step 1: 更新 README 功能清单**

在功能列表加入：输入时跟随前台文本光标、缩小到 20%、避开输入框和 IME 候选词，停止输入后恢复原位置和缩放。

- [ ] **Step 2: 运行自动化回归**

运行：`$ErrorActionPreference = 'Stop'; $env:QT_QPA_PLATFORM = 'offscreen'; python selftest_v2.py`

预期：`ALL PASS`。

- [ ] **Step 3: 运行语法检查**

运行：`$ErrorActionPreference = 'Stop'; python -m py_compile pet_v2.py selftest_v2.py`

预期：命令无输出且退出码为 0。

- [ ] **Step 4: 执行 Windows 手工验收**

运行：`$ErrorActionPreference = 'Stop'; python pet_v2.py`，依次在记事本、浏览器、IDE 和中文 IME 中输入，检查光标下方定位、候选词避让、底部边缘回退、多显示器定位、1 秒后恢复原位置/缩放。

- [ ] **Step 5: 提交文档和最终验收结果**

```powershell
$ErrorActionPreference = 'Stop'
& 'C:\Program Files\Git\bin\git.exe' add -- README.md
& 'C:\Program Files\Git\bin\git.exe' commit -m '补充输入光标跟随功能说明'
```
