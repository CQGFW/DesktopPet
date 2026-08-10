# DesktopPet v1.3.1「代码审查与重构」开发过程记录

> **时间**：2026-08-10（继 v1.3.0「UI Automation 定位微信候选条」之后）
> **需求**：分析现有代码有哪些可以改进的地方，然后全部落地。
> **成果**：修复 5 个性能 / 正确性问题，1612 行单文件拆成 `desktoppet/` 包（14 个模块），
> 自测脚本迁移到 pytest（135 个用例），新增偏好持久化与调试日志。发布 GitHub Release **v1.3.1**。

---

## 1. 起点：一次代码审查

本次没有新功能需求，起点是「分析现在的代码有什么可以改进的地方」。通读 `pet_v2.py`（1612 行）
与 `selftest_v2.py`（563 行）后列出 17 项，按优先级分成五组：性能与正确性、健壮性、结构、测试、体验。

其中 4 项被判定为应当最先动：改动都不大，但影响真实运行表现。用户先批准了这 4 项，
随后要求把剩下的 13 项也全部完成。

## 2. 第一批：性能与正确性

| # | 问题 | 处理 |
| --- | --- | --- |
| 1 | `query_input_context` 里第一次 `_wechat_candidate_rect(caret)` 的结果在两行后被无条件覆盖 | 删除该调用，每次查询少一整轮 `EnumWindows` + 子窗口递归 |
| 2 | 敲英文时 `_uia_candidate_rect` 每次轮询都跑 6×6 探测网格（约 108 次跨进程 COM 调用） | 探测链抽成 `discover_candidate()`，外面包 200ms 节流缓存 |
| 3 | 每次按键都触发一次完整的 `query_input_context()` | 跟随激活后按键只续期空闲计时，位置交给已在运行的轮询定时器 |
| 5 | 宠物会把自己的气泡当成 IME 候选框来躲 | 按 `GetCurrentProcessId()` 排除自身窗口，删掉硬编码的 exe 名判断 |

**关于 #2 的关键取舍**：最直接的优化是「先判断是否真的在组字，不在就跳过探测」。
但微信输入法（WeType）走 TSF 而非传统 IMM，`ImmGetCompositionStringW` 未必能反映其组字状态——
而 UIA 兜底这条路径正是 v1.3.0 为它专门加的。因此**没有动任何检测逻辑**，
只在外面加节流：三条探测路径的顺序、判定阈值、探测网格全部保持原样，降低的只是频率。
候选条一旦弹出会稳定停留数百毫秒，复用「候选区在哪」这个结论是安全的；
前台窗口切换或光标移动超过 24px 时立即失效重探。

**关于 #5**：`Bubble` 是无边框 + 置顶 + 分层的 Tool 窗口，正好满足 `is_generic_popup_style` 的全部条件，
尺寸也落在候选条的判定区间内。原来靠 `normalized_name not in {"desktoppetv2.exe", ""}` 排除，
以 `python pet_v2.py` 方式运行时进程名是 `python.exe`，直接绕过。按 PID 排除不受运行方式与改名打包影响。

**实测**：1 秒内 20 次轮询，全量探测从 20 次降到 5 次；跟随激活后 8 次按键触发 0 次查询（原为 8 次）。
按每秒 8 键估算，输入跟随的跨进程调用量约为改动前的 1/10。

## 3. 第二批：拆分、健壮性与体验

用户要求「未动的部分全部改动」后，重新排了顺序：**先做机械拆分，再往新模块里落功能改动**。
理由是拆分本身不改行为，可以用现有自测当安全网验证；若先改功能再拆分，两件事的风险会缠在一起。

### 3.1 模块拆分（#9）

1600 行手工搬运容易出错，改用一次性脚本按行区间切分，并用一张重命名表统一处理跨模块符号
（`_configure_input_apis` → `winapi.configure` 等），生成时再去掉模块自身的前缀。

```
desktoppet/
  config.py       应用级常量、素材路径      settings.py      QSettings 偏好持久化
  debuglog.py     可选调试日志              winapi.py        Win32 ctypes 声明层
  uia.py          UI Automation（COM）      ime.py           候选框探测 + 节流缓存
  placement.py    落位几何（纯函数）        input_follow.py  插入符 / 焦点 / 候选区采集
  keyboard.py     全局键盘钩子              sprite.py        素材分层
  bubble.py       气泡                      pet.py / app.py  主窗口 / 入口
pet_v2.py         启动入口（README、spec、快捷方式都指向它）
```

一个容易踩的坑：`resource_path` 原来用 `os.path.dirname(__file__)` 定位素材，
移进 `desktoppet/config.py` 后目录深了一层，必须向上取一级，否则打包后找不到 `cat_soft.png`。

拆完先把旧自测的引用批量指向新模块，跑通 21 组用例（含逐像素的分层还原比对），
确认拆分未改变行为，再继续。

### 3.2 健壮性

- **#4 PID 缓存**：Windows 会复用 PID，永久缓存会把新进程认成已退出的旧进程。逐窗口校验创建时间
  代价太高，改用 30 秒 TTL + 512 条上限（超限先清过期项，仍超限整表丢弃）。误判最多存在一个 TTL 窗口。
- **#6 调试日志**：11 处静默 `except` 补上 `debuglog.exception()`，返回值与降级行为一行未动。
  默认完全静默（打包后无控制台），`DESKTOPPET_DEBUG=1` / `DESKTOPPET_LOG=路径` 打开。
- **#7 COM 生命周期**：`CoInitializeEx` 的 HRESULT 不再忽略，区分「本模块持有」与 `RPC_E_CHANGED_MODE`；
  新增 `shutdown()`，且**只在自己初始化过时**才 `CoUninitialize`——否则会拆掉宿主的 COM 环境。
- **#8 非 Windows 平台**：`KeyListener._run` 原来第一行取 `ctypes.windll` 就抛异常，线程静默死掉而菜单
  仍显示「已开启」。改走统一的 `_fail()`，且**刻意保持在钩子线程内 emit**：跨线程是队列投递，
  改成同步 emit 会让槽在 `Pet.__init__` 中途运行、碰到尚未初始化的属性。

### 3.3 结构与体验

- **#10**：`80/1200/24/180/240` 这组候选框判定阈值原本在窗口枚举与 UIA 探测两处各写一遍，
  合并为 `placement.candidate_score()`。
- **#11**：`_set_scale(self.scale)` 这个「传当前值只为触发重建」的写法拆成 `_rebuild_geometry()`。
- **#12**：`APP_VERSION` 原本从未被引用，现在既显示在右键菜单标题，也由 spec 在打包时生成
  `version_info.txt`，消除三处版本号漂移。
- **#15**：四个开关 + 缩放比例持久化。存盘时特意用**进入输入跟随前**的原始比例，否则会越存越小；
  滚轮改动走 800ms 去抖。`Pet(persist=False)` 供测试使用，不读写真实注册表。
- **#17**：气泡停留时长按字数在 2~6 秒间浮动；纵向也收进屏幕（原来只钳制了 x）。

### 3.4 一处有意的行为变更（#16）

给输入跟随加了菜单开关，并让它服从系统「减少动态效果」。

这与旧自测里一条明确的断言相反——原测试写着「减少动态效果不应阻止输入跟随」。
改变它的理由：输入跟随会让宠物在屏幕上大幅跳动，是这个程序里最显眼的动效，
而呼吸、转头、点击动画、自动走动都已经服从该设置，唯独它豁免并不自洽。
现在的处理与自动走动一致：开启时抑制、关闭时恢复，另外给了独立开关。

**这条是有意为之，已在交付时单独标注**，若当初的豁免是刻意设计，可以单独退回。

## 4. 测试迁移（#13 / #14）

`selftest_v2.py` 是 563 行平铺断言、共用一个 `Pet` 实例、第一个失败就中断其余全部用例。
迁移到 `tests/` 下 13 个模块、135 个用例，1.2 秒跑完：

- 每个用例一只全新宠物（`Pet(persist=False)`），互不继承状态；
- QSettings 通过 session 级 autouse fixture 重定向到临时目录，不污染开发机真实偏好；
- 退出路径这类重复结构改用 `@pytest.mark.parametrize`（stop / click / press / wheel / focus_out）；
- 字面量换成模块常量（如 `66` → `config.INPUT_UNKNOWN_CANDIDATE_GAP`）；
- 补了原来完全没有的覆盖：偏好持久化往返与损坏值兜底、PID 缓存 TTL 与容量、候选框节流缓存的失效条件。

## 5. 教训：一个 135 个用例全绿却让功能彻底失效的 bug

拆分时的重命名把 `_uia_client()` 改成了 `client()`，于是两个调用点变成：

```python
def input_rects():
    client = client()          # Python 判定 client 是局部变量 -> UnboundLocalError
```

它发生在 `try` 之前，异常一路冒泡到 `query_input_context` 的兜底 `except` 被吞掉，
**结果是输入跟随在真实 Windows 上完全不工作，而全部用例照常通过**——
因为这两条路径需要真实的前台插入符和 IME 候选条才会走到，offscreen 测试根本碰不到。

发现它靠的是收尾时跑的一遍 `pyflakes`：

```
uia.py:134:14: local variable 'client' defined in enclosing scope on line 56 referenced before assignment
```

修复后补了 `tests/test_uia.py`，锁住「拿不到 UIA 客户端时应安静返回空值而非抛异常」这一契约，
并**把 bug 还原跑了一遍**确认该用例确实会失败（报 `UnboundLocalError`），再还原回来。

三条可复用的经验：

1. **大范围机械重命名后必须过一遍静态检查**。测试覆盖不到的分支，靠人眼和用例都拦不住，
   而 `referenced before assignment` 这类问题静态分析一秒就能报出来。
2. **「捕获一切的 except」会把重构事故伪装成功能降级**。`except Exception: return None` 让
   `UnboundLocalError` 看起来和「这台机器上探测不到候选框」一模一样。本次补的调试日志正好覆盖这个盲区。
3. **补测试时要验证它真能失败**。把 bug 还原一次，确认用例变红，才算真正锁住。

## 6. 发布

- 版本号：`desktoppet/__init__.py` 的 `APP_VERSION` 改为 `1.3.1`，`version_info.txt` 由 spec 自动生成；
- 打包：`python -m PyInstaller DesktopPetV2.spec` → `dist/DesktopPetV2.exe`（单文件、无控制台）；
- 发布：GitHub Release **v1.3.1**。

## 7. 本次改动清单

| 类别 | 内容 |
| --- | --- |
| 性能 | 删除重复窗口枚举；候选框探测 200ms 节流；按键不再各自触发跨进程查询 |
| 正确性 | 按 PID 排除自身窗口；PID 名缓存加 TTL 与上限；修复 `client` 遮蔽导致的 `UnboundLocalError` |
| 健壮性 | 可选调试日志；COM 配对释放；非 Windows 下钩子失败可上报 |
| 结构 | 单文件 → 14 个模块；候选框阈值合一；`_rebuild_geometry`；版本号单点化 |
| 测试 | pytest 迁移，135 个用例；新增持久化 / 缓存 / UIA 降级覆盖 |
| 体验 | 偏好持久化；输入跟随开关并服从「减少动态效果」；气泡时长与纵向钳制 |
