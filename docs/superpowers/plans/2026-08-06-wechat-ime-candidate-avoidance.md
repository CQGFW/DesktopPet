# 微信输入法候选框避让 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 识别微信输入法 2.1.1.8 的独立候选窗口，使缩小后的宠物避开候选词框并尽量靠近输入光标。

**Architecture:** 保持 `pet_v2.py` 单文件运行结构。Win32 层用 `EnumWindows`、进程映像名和窗口矩形发现 `wetype_renderer.exe` 的可见候选窗口；纯函数负责筛选邻近光标的合理矩形，定位函数在候选框遮挡下方时优先尝试左右位置。传统 IMM 查询继续保留为其他输入法的兼容路径。

**Tech Stack:** Python 3.12、ctypes Win32 API、PySide6 `QRect`/`QPoint`、现有 `selftest_v2.py`、PyInstaller 6.21。

## Global Constraints

- 对所有前台应用的文本控件生效，包括记事本、浏览器、IDE、聊天框等。
- 复用现有 Windows 全局低阶键盘钩子，不新增第三方 Python 依赖。
- 默认使用 1000ms 无按键作为输入结束判定。
- 输入跟随不受“键盘互动”开关和“减少动态效果”设置影响。
- 用户点击、拖拽或滚轮操作宠物时立即结束输入跟随。
- 微信输入法窗口识别只接受可见、尺寸合理且邻近当前光标的候选窗口。
- 所有 CLI 命令使用 PowerShell 7，首行设置 `$ErrorActionPreference = 'Stop'`；文件读取显式使用 `-Encoding UTF8`。

## File Structure

- Modify: `pet_v2.py` - 声明 Win32 枚举/进程查询 API，发现微信输入法候选窗口，合并候选区来源并计算安全位置。
- Modify: `selftest_v2.py` - 覆盖候选窗口纯筛选、微信候选区优先级和左右避让几何。
- Build: `dist/DesktopPetV2.exe` - 使用现有 `DesktopPetV2.spec` 重新生成，不修改 spec。

---

### Task 1: 发现微信输入法候选窗口

**Files:**
- Modify: `pet_v2.py:189-231, 412-480`
- Test: `selftest_v2.py:44-59`

**Interfaces:**
- Consumes: `caret: QRect`、`EnumWindows` 返回的可见顶层窗口、`wetype_renderer.exe` 进程映像名。
- Produces: `_select_wechat_candidate(caret: QRect, windows: list[tuple[str, QRect]]) -> QRect | None`、`_wechat_candidate_rect(caret: QRect) -> QRect | None`。

- [ ] **Step 1: 写入失败的候选窗口筛选测试**

在 `selftest_v2.py` 的 IMM 坐标测试后加入：

```python
wechat_windows = [
    ("wetype_renderer.exe", QRect(216, 134, 572, 44)),
    ("wetype_renderer.exe", QRect(1400, 700, 500, 44)),
    ("other_overlay.exe", QRect(210, 130, 580, 50)),
]
wechat_caret = QRect(226, 105, 2, 22)
assert m._select_wechat_candidate(wechat_caret, wechat_windows) == QRect(216, 134, 572, 44)
assert m._select_wechat_candidate(
    wechat_caret, [("wetype_renderer.exe", QRect(216, 134, 20, 10))]) is None
```

- [ ] **Step 2: 运行自测并确认因函数不存在而失败**

Run:

```powershell
$ErrorActionPreference = 'Stop'
python selftest_v2.py
```

Expected: FAIL，提示 `pet_v2` 没有 `_select_wechat_candidate`。

- [ ] **Step 3: 声明枚举和进程查询 API**

在 `pet_v2.py` 的 Win32 结构与全局状态附近加入：

```python
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WECHAT_IME_PROCESSES = {"wetype_renderer.exe"}
_WINDOW_PROCESS_NAMES = {}
```

在 `_configure_input_apis()` 中为 `EnumWindows`、`IsWindowVisible`、`OpenProcess`、`QueryFullProcessImageNameW` 和 `CloseHandle` 设置 `restype`/`argtypes`。`OpenProcess` 只申请 `PROCESS_QUERY_LIMITED_INFORMATION`，任何失败均返回空结果。

```python
user32.EnumWindows.restype = wintypes.BOOL
user32.EnumWindows.argtypes = (WNDENUMPROC, wintypes.LPARAM)
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = (wintypes.HWND,)

kernel32 = ctypes.windll.kernel32
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD))
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
```

- [ ] **Step 4: 实现纯筛选和 Win32 枚举**

在 `_ime_candidate_rect()` 后加入：

```python
def _select_wechat_candidate(caret, windows):
    nearby = []
    for process_name, rect in windows:
        if process_name.lower() not in WECHAT_IME_PROCESSES:
            continue
        if not (80 <= rect.width() <= 1200 and 24 <= rect.height() <= 180):
            continue
        dx = max(rect.left() - caret.right(), caret.left() - rect.right(), 0)
        dy = max(rect.top() - caret.bottom(), caret.top() - rect.bottom(), 0)
        if dx <= 240 and dy <= 240:
            nearby.append((dx * dx + dy * dy, -rect.width(), rect))
    return min(nearby, key=lambda item: (item[0], item[1]))[2] if nearby else None
```

实现 `_window_process_name(hwnd)`：通过 `GetWindowThreadProcessId` 取得 PID，使用 `_WINDOW_PROCESS_NAMES` 缓存；未命中时调用 `OpenProcess` 和 `QueryFullProcessImageNameW`，保存小写 basename，最后始终 `CloseHandle`。

```python
def _window_process_name(hwnd):
    process_id = wintypes.DWORD()
    if not ctypes.windll.user32.GetWindowThreadProcessId(
            hwnd, ctypes.byref(process_id)):
        return None
    if process_id.value in _WINDOW_PROCESS_NAMES:
        return _WINDOW_PROCESS_NAMES[process_id.value]

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, process_id.value)
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)):
            return None
        name = os.path.basename(buffer.value).lower()
        _WINDOW_PROCESS_NAMES[process_id.value] = name
        return name
    finally:
        kernel32.CloseHandle(handle)
```

实现 `_wechat_candidate_rect(caret)`：`EnumWindows` 回调只收集 `IsWindowVisible`、`_window_rect()` 有效且进程名可读的窗口，然后交给 `_select_wechat_candidate()`；回调和枚举异常均返回 `None`。

```python
def _wechat_candidate_rect(caret):
    if not _configure_input_apis():
        return None
    windows = []
    user32 = ctypes.windll.user32

    @WNDENUMPROC
    def collect(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            process_name = _window_process_name(hwnd)
            if process_name in WECHAT_IME_PROCESSES:
                rect = _window_rect(hwnd)
                if rect is not None:
                    windows.append((process_name, rect))
        return True

    try:
        if not user32.EnumWindows(collect, 0):
            return None
        return _select_wechat_candidate(caret, windows)
    except Exception:
        return None
```

- [ ] **Step 5: 将微信候选窗口合并到输入上下文**

在 `query_input_context()` 中使用真实微信窗口优先、IMM 兼容回退：

```python
wechat_candidate = _wechat_candidate_rect(caret)
candidate = (wechat_candidate if wechat_candidate is not None
             else _ime_candidate_rect(ime_hwnd))
```

- [ ] **Step 6: 运行测试与编译检查**

Run:

```powershell
$ErrorActionPreference = 'Stop'
python selftest_v2.py
python -m py_compile pet_v2.py selftest_v2.py
```

Expected: `ALL PASS`，`py_compile` 无输出且退出码为 0。

- [ ] **Step 7: 提交候选窗口发现实现**

```powershell
$ErrorActionPreference = 'Stop'
& 'C:\Program Files\Git\cmd\git.exe' add pet_v2.py selftest_v2.py
& 'C:\Program Files\Git\cmd\git.exe' commit -m '识别微信输入法候选窗口'
```

---

### Task 2: 候选框遮挡时优先左右避让

**Files:**
- Modify: `pet_v2.py:483-528`
- Test: `selftest_v2.py:19-42`

**Interfaces:**
- Consumes: `_input_safe_position(caret, focus, candidate, pet_size, screen, gap=INPUT_GAP)` 的现有参数。
- Produces: 屏幕内且不与候选框/紧凑输入框相交的 `QPoint`；候选框遮挡首选下方位置时优先返回候选框左侧或右侧。

- [ ] **Step 1: 修改几何测试使其表达左右优先契约**

用截图几何替换原先“必须位于候选框下方”的断言：

```python
wechat_screen = QRect(0, 0, 864, 316)
wechat_caret = QRect(226, 105, 2, 22)
wechat_candidate = QRect(216, 134, 572, 44)
wechat_pos = m._input_safe_position(
    wechat_caret, QRect(0, 0, 864, 316), wechat_candidate,
    QSize(60, 52), wechat_screen)
wechat_pet = QRect(wechat_pos, QSize(60, 52))
assert not wechat_pet.intersects(wechat_candidate.adjusted(-m.INPUT_GAP, -m.INPUT_GAP,
                                                            m.INPUT_GAP, m.INPUT_GAP))
assert wechat_pet.right() < wechat_candidate.left()
assert abs(wechat_pet.center().y() - wechat_caret.center().y()) <= 1
```

保留原候选框位于输入框下方、屏幕边缘和整页文档焦点测试；将其断言改为只要求屏幕内且不相交，避免固定为下方唯一策略。

- [ ] **Step 2: 运行自测并确认旧算法失败**

Run:

```powershell
$ErrorActionPreference = 'Stop'
python selftest_v2.py
```

Expected: FAIL，截图几何返回候选框下方，而不是左侧。

- [ ] **Step 3: 实现候选框专用的左右优先候选顺序**

在 `_input_safe_position()` 中保留紧凑输入框和候选框的扩大矩形。先测试光标正下方原始位置；若只因候选框碰撞，按以下坐标生成位置：

```python
side_y = caret.center().y() - height // 2
candidate_positions = [
    (candidate.left() - gap - width, side_y),
    (candidate.right() + gap + 1, side_y),
    (center_x, candidate.bottom() + gap + 1),
    (center_x, caret.top() - gap - height),
]
```

若下方位置不与任何避让矩形相交，仍立即返回下方位置。每个候选位置都先限制到 `screen`，再要求 `screen.contains(rect)` 且不与任何扩大后的避让矩形相交。候选框未提供时保持当前 13px 下方定位。

- [ ] **Step 4: 运行全量自测和编译检查**

```powershell
$ErrorActionPreference = 'Stop'
python selftest_v2.py
python -m py_compile pet_v2.py selftest_v2.py
& 'C:\Program Files\Git\cmd\git.exe' diff --check
```

Expected: `ALL PASS`，编译与空白检查通过。

- [ ] **Step 5: 提交定位修复**

```powershell
$ErrorActionPreference = 'Stop'
& 'C:\Program Files\Git\cmd\git.exe' add pet_v2.py selftest_v2.py
& 'C:\Program Files\Git\cmd\git.exe' commit -m '避让微信输入法候选词框'
```

---

### Task 3: 重新打包并完成 Windows 验收

**Files:**
- Verify: `pet_v2.py`
- Verify: `selftest_v2.py`
- Build: `dist/DesktopPetV2.exe`

**Interfaces:**
- Consumes: Tasks 1-2 已通过测试的源码。
- Produces: 包含微信输入法候选框避让修复的 Windows 单文件可执行程序。

- [ ] **Step 1: 完成最终自动验证**

```powershell
$ErrorActionPreference = 'Stop'
python selftest_v2.py
python -m py_compile pet_v2.py selftest_v2.py
& 'C:\Program Files\Git\cmd\git.exe' diff --check
```

Expected: `ALL PASS`，所有命令退出码为 0。

- [ ] **Step 2: 使用现有 spec 重新构建**

```powershell
$ErrorActionPreference = 'Stop'
python -m PyInstaller --noconfirm DesktopPetV2.spec
```

Expected: 日志包含 `Building EXE ... completed successfully` 和 `Build complete`。

- [ ] **Step 3: 检查产物和工作区**

```powershell
$ErrorActionPreference = 'Stop'
Get-Item -LiteralPath 'dist\DesktopPetV2.exe' | Select-Object FullName,Length,LastWriteTime
& 'C:\Program Files\Git\cmd\git.exe' status --short
```

Expected: EXE 时间晚于源码提交；工作区无未提交源码改动。

- [ ] **Step 4: 手工验收微信输入法**

启动新 `dist\DesktopPetV2.exe`，在文档编辑器中使用微信输入法连续输入拼音，确认：

- 候选框出现时宠物不与候选词框相交；
- 截图所示左侧空间可用时宠物位于候选框左侧；
- 左右空间不足时宠物位于候选框下方或上方的屏幕内安全位置；
- 候选框消失后宠物重新贴近光标下方约 13px；
- 停止输入 1 秒后恢复原位置和缩放。

- [ ] **Step 5: 记录最终状态**

若手工验收无需再改源码，不新增空提交；在交付说明中记录自动测试结果、EXE 路径以及需要退出旧实例后再启动新构建。
