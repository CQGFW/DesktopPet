# 可调整的输入跟随大小 Implementation Plan

> 依据：`docs/superpowers/specs/2026-08-10-input-follow-scale-design.md`（已确认）
> 规模：约 40 行生产代码，集中在 `config.py` / `settings.py` / `pet.py`。

## Global Constraints

- 不触碰 Win32 / UIA / 候选框探测各层，改动应能被 offscreen 测试完全覆盖。
- 进入 / 退出跟随的时机、落位避让、还原路径不变；`input_saved_scale` 职责不变。
- 每个 Task 结束后跑 `python -m pytest`，保持全绿。
- 测试先行：Task 1 写的用例应当先失败，再由后续 Task 转绿。

---

### Task 1: 先写测试（应失败）

在 `tests/test_input_follow.py` 增加档位相关用例，在 `tests/test_settings.py` 增加持久化用例，
在 `tests/test_menu.py` 增加子菜单用例。

- `test_follow_scale_equals_the_selected_choice`：选中每个档位，进入跟随后 `pet.scale` 等于该档位。
- `test_follow_scale_is_absolute_not_relative`：把平时大小分别设为 `MAX_SCALE` / `MIN_SCALE`，
  跟随大小仍等于档位（这条是与旧相对倍率行为的分界线）。
- `test_default_choice_is_in_choices`：`INPUT_SCALE_DEFAULT in INPUT_SCALE_CHOICES`。
- 设置：`input_scale` 往返；不在 `INPUT_SCALE_CHOICES` 内的值退回默认。
- 菜单：子菜单含四个档位、互斥、当前档位选中；「输入跟随」关闭时子菜单仍可用。

同时把现有 `tests/test_input_follow.py:23` 对 `config.INPUT_SCALE_FACTOR` 的引用改为按档位判定。

**验收**：新用例失败（`AttributeError` / 断言不成立），其余用例仍全绿。

---

### Task 2: config 档位常量

`desktoppet/config.py`：删除 `INPUT_SCALE_FACTOR`，新增

```python
INPUT_SCALE_CHOICES = (0.20, 0.25, 0.30, 0.40)
INPUT_SCALE_DEFAULT = 0.20
```

注释写明这是绝对比例、且允许低于 `MIN_SCALE`（跟随是独立的缩放域）。

**验收**：`test_default_choice_is_in_choices` 转绿。

---

### Task 3: settings 持久化

`desktoppet/settings.py`：

- `load()` 返回值扩展为 `(flags, scale, input_scale)`；
- 校验 `input_scale` 必须落在 `config.INPUT_SCALE_CHOICES` 内，否则退回 `INPUT_SCALE_DEFAULT`；
- `save(flags, scale, input_scale)` 增加一个参数。

**验收**：`tests/test_settings.py` 的新用例转绿。

---

### Task 4: Pet 状态与菜单

`desktoppet/pet.py`：

- `__init__` 解包三元组，初始化 `self.input_follow_scale`；
- 在「输入跟随」之后构建子菜单「输入跟随大小」，`QActionGroup` 互斥，当前档位 `setChecked`，
  沿用「创建 → setChecked → 连信号」顺序；
- 槽 `_set_input_follow_scale(value)`：赋值 + `_schedule_save()`（不重新缩放当前跟随，理由见 spec）；
- `_input_on_key` 中 `self._set_scale(self.input_saved_scale * config.INPUT_SCALE_FACTOR)`
  改为 `self._set_scale(self.input_follow_scale)`；
- `_current_flags()` 不变（档位不是 bool），`save_settings()` 传入 `self.input_follow_scale`。

**验收**：`tests/test_input_follow.py` 与 `tests/test_menu.py` 的新用例转绿，全套测试通过。

---

### Task 5: 文档与验收

- `README.md` 功能清单补充「输入跟随大小可在右键菜单调整」。
- 全量 `python -m pytest`；`python -m pyflakes desktoppet/*.py tests/*.py`。
- 端到端冒烟：offscreen 跑一次 `app.main()` 确认启动与退出正常。

**验收**：测试全绿、静态检查无输出、冒烟 exit code 0。
