# `lang`：公式与技能脚本

规则包里所有能算的东西都用这门小语言写：推导值、上下限、检定的骰子和目标值、条目的修正、施放时间和冷却时间、技能脚本。

**语法就是 Python 的一个子集。** 用 Python 自带的 `ast` 把文字解析成语法树，但不交给 Python 执行：只认下面列出的写法，求值、名字、掷骰都是自己做的。所以不会跑任何外部代码，也不能 `import`。

- 依赖：无。这个包不认识角色卡和规则包；名字指什么、表怎么查、骰子怎么掷，都由调用方（`rules`）以回调传进来。
- 文件：`formula.py` 是公式（解析、求值、写回文本），`script.py` 是技能脚本。
- 单独测试：`uv run pytest tests/lang`

下面先讲公式，再讲技能脚本，最后是名字的含义（由 `rules` 决定）和出错代码。

---

## 一、公式

一条公式算出一个值：数字，或一段文字。

### 1. 字面量

| 写法 | 说明 |
| --- | --- |
| `3`、`2.5` | 数字 |
| `"warrior"`、`'warrior'` | 文字，单引号双引号都行 |
| `True`、`False` | 就是 1 和 0 |

### 2. 运算

和 Python 一样，按优先级从高到低：

| 运算 | 说明 |
| --- | --- |
| `( … )`、函数调用、名字、掷骰 `3d6` | 掷骰是一个整体：`2d6 * 5` 是 `(2d6) * 5` |
| `x ** y` | 乘方 |
| `-x` | 取负 |
| `*`、`/`、`//`、`%` | 乘、除、整除（向下取整）、余数（和除数同号：`-1 % 3` 是 2）；除以 0 报错 |
| `+`、`-` | |
| `<` `<=` `>` `>=` `==` `!=` | 成立得 1，不成立得 0；可以连写：`1 < x <= 3` |
| `not x` | 不成立得 1 |
| `a and b`、`a or b` | 都成立 / 有一个成立得 1；短路（后面的不算） |
| `a if 条件 else b` | 条件成立取 a，否则取 b；没选中的一边不算（不会掷骰、不会报错） |

- 比较相等要写 `==`。单个 `=` 报 `formula.single_equals`。
- 文字只能用 `==` / `!=` 比较，参与加减乘除会报错。
- 真假：0 和空文字是假，其余是真。

### 3. 掷骰

| 写法 | 含义 |
| --- | --- |
| `3d6`、`3D6` | 3 颗 6 面骰求和 |
| `d20`、`d%` | 省略个数就是 1 颗；`d%` 是 `d100` |
| `1d str`、`1dstr`、`2d(str + 1)`、`1d lookup(表, x)` | 面数可以是名字、括号或函数调用 |
| `dice(level, luck)` | 个数不是数字时用这个：level 颗、每颗 luck 面 |
| `highest(4, 6, 3)` | 掷 4 颗 6 面骰，取最高的 3 颗之和；`lowest` 取最低的 |

- `NdM` 这些写法在交给 Python 之前改写成 `dice(N, M)`。引号里和 `#` 注释里的不动。
- 个数和面数先四舍五入（.5 远离零）。个数 0～1000，面数 1～100000，超出报错。
- **只有能掷骰的地方才能掷骰**：检定的骰子、KP 的临时检定和自由掷骰、技能脚本的数量和分钟、掷骰公式列。
- 推导值、上下限、初值、每分钟变化、检定目标值和结果条件、施放时间、冷却时间、`modify` 的新值公式、脚本里的 `if` 条件，每次查看都要重新算，或者没有地方记点数，所以不能掷骰。写了会报 `formula.dice_not_allowed`。

### 4. 函数

| 函数 | 说明 |
| --- | --- |
| `abs(x)` `floor(x)` `ceil(x)` `trunc(x)` `sign(x)` `sqrt(x)` | 绝对值、向下取整、向上取整、向零取整、符号（1 / -1 / 0）、平方根 |
| `round(x)` | 四舍五入，.5 远离零（不是 Python 的银行家舍入） |
| `pow(x, y)` | 等于 `x ** y` |
| `mod(x, y)` | 等于 `x % y` |
| `min(a, b, …)` `max(a, b, …)` | 最小、最大 |
| `clamp(x, lo, hi)` | 把 x 限制在 lo..hi |
| `lookup(表, key)` | 查规则包的表。范围表取“不超过 key 的最大一行”，精确表要求完全相等 |
| `count(分组)` | 分组里有几条 |
| `count(分组.列, 值)` | 这一列等于这个值的有几条（数字或文字都行） |
| `sum(分组.列)` | 这一列加起来是多少 |
| `dice(n, s)` | 掷骰，等于 `NdM` |
| `highest(n, s, k)` `lowest(n, s, k)` | 掷骰，见上 |

- 只能调用这张表里的函数。Python 自己的函数（`print`、`len`、`__import__`……）一律报 `formula.unknown_function`。
- `lookup` 的第一个参数是表名，`count` / `sum` 的第一个参数是分组引用，它们都不是普通名字。
- 分组前面可以加 `<模板>.` 或 `target.`，例如 `count(companion.traits.rank, 3)`。
- `count` / `sum` 统计时跳过没填的列；“使用时填写”的列不能统计。
- 不支持的 Python 写法（列表、下标 `x[0]`、`lambda`、`in`、f-string、关键字参数……）报 `formula.unsupported`。

---

## 二、技能脚本

条目（技能）被使用、并且 KP 判定生效时，引擎执行的一串语句。

```
# 吸血：打对象，给自己回血
target.damage(this.damage)
self.add(hp, 5)

target.add(shield, this.level * 4, 30); target.sub(mp, 10)
target.modify(move_speed,
              move_speed * 0.5, 10)        # 括号没关上可以换行接着写
```

### 1. 书写规则

就是 Python 的写法：

- 一行一句，也可以用 `;` 隔开。
- `#` 到行尾是注释（引号里的 `#` 不算）。
- 括号没关上时，换行算同一句。
- 空行和只有注释的行忽略；整段为空表示没有脚本。`pass` 什么都不做（例如空着的 `else`）。
- 能写动作句、`if` 和局部变量（`heal = 2 + this.level * 3`，后面的句子直接用 `heal`；只算一次，不能掷骰，变量名不能叫 `self` / `target` / `this`）。循环、`def`、`+=` 这些报 `script.bad_statement`。

### 2. 语句

每句都写成 `<对象>.<动作>(参数, …)`。

**对象：**
- `self`：使用者自己。
- `target`：使用时选的对象，可以是任何人，也可以是自己。
- 没有对象（KP 声明时 target 为空）时，`target` 的句子跳过，只执行 `self` 的句子。

**动作：**

| 动作 | 参数 | 效果 |
| --- | --- | --- |
| `damage(数量)` | 公式 | 受到伤害：先扣 `shield`（有这个字段时），剩下的扣 `hp` |
| `add(字段, 数量)` | 字段名，公式 | 增加 |
| `add(字段, 数量, 分钟)` | 字段名，公式，公式 | 限时增加（例如护盾）：到期时扣回加上去还剩下的部分 |
| `sub(字段, 数量)` | 字段名，公式 | 减少 |
| `set(字段, 数量)` | 字段名，公式 | 设为 |
| `modify(推导值, 新值公式, 分钟)` | 推导值名，公式，公式 | 加一条限时修正，到期消失 |

- 字段参数只写名字，比如 `hp`，不能带前缀；它指的是这句的对象身上的字段。
- `add`、`sub`、`set` 只能改运行值（数值或资源）。结果会截断在这个字段的上下限之内。
- `modify` 只能修正推导值。
- 动作写死在 `VERBS` 里。治疗就是 `add(hp, …)`，不另设只属于某套规则的动作。

### 3. 条件分支

```
if target.template == "monster":
    target.add(mp, 2 * this.mp_spent)
elif target.template == "boss":
    target.add(mp, this.mp_spent)
else:
    self.add(mp, this.mp_spent)
self.sub(mp, 1)          # 不缩进：不管走哪一支都执行
```

- 写法和 Python 一样：`if 条件:`，下面缩进的几行是这一支；后面可以接任意个 `elif 条件:`，最后可以有一个 `else:`。只有一句时可以写在同一行：`if x > 1: self.add(hp, 1)`。
- 从上往下，第一个成立的条件那一支执行，其余跳过；都不成立就执行 `else`（没有 `else` 就什么都不做）。
- 缩进几个空格都行（Tab 算 4 个），但同一支里的行要对齐。分支里可以再套分支。
- `if` 后面的条件是一条公式，0 和空文字算不成立。
- 条件在声明使用时算，**不能掷骰**，因为条件掷出来的点数没有地方记进日志。要按概率触发，就把掷骰放进数量里，例如 `target.damage(10 if 1d100 <= 30 else 0)`。
- 没有对象时，条件里用到 `target.` 的整个 `if … elif … else` 都跳过。
- 编辑框里按 Tab 插入 4 个空格；回车会保持这一行的缩进，行尾是冒号时再多缩进一级。

### 4. 求值时机

1. **KP 规划时声明使用：** 引擎立刻把每一句算好，条件也在这时判断。数量和分钟当场掷骰，点数记进 `entry_used` 事件。`modify` 的新值公式会被“冻结”：除了被修正的推导值自己的名字，其余名字都换成此刻的值。
   - 例如使用者 `str` 是 12，`target.modify(move_speed, move_speed + str, 10)` 存成 `(move_speed + 12)`。之后在带着这条修正的角色身上，用他当时的 `move_speed` 算。
2. **KP 裁定生效：** 引擎照着算好的数值，一句一句执行。没生效（没打中、被挡住）的话只扣使用时的消耗，冷却照样开始。
3. 分钟换算成游戏内秒。施放时间、冷却时间和脚本里的持续时间都按分钟。

---

## 三、技能设置

条目的另一半：引擎在 KP 之前就按它检查和执行，不用 KP 判断。一行一项，`名字 = 值`；在 IDE 里打开条目时，这个分组用得上的项会预先填好。

```
target = "single"                # single 要选一个对象 / self 只能对自己用 / none 没有对象
range = 30 + this.level * 5      # 射程（米）；None 表示不限
visible = True                   # 对象必须在使用者此刻的感知里
requires = not silenced          # 使用条件，不成立就不能用
noise = 20                       # 动静范围（米）：范围内的其他玩家会察觉到有人用了它
cast_time = 0.5                  # 施放时间（分钟），不到 1 算瞬发
cooldown = 60                    # 冷却（分钟）
shape = cone(length=10, angle=60)
placement = placement(radius=3, perceive=0.5, charges=1, duration=60, notify=True)
```

- 语法是 Python 的赋值（`lang/config.py` 解析）；值可以是公式（能用 `this.列`），`None` 表示不设，没写的项取默认。
- 设置和技能脚本可以互相引用名字：设置里能用别的项（`noise = range * 2`）和脚本最外层的变量，脚本里能直接用设置的项（`target.damage(range)`）。不分先后，用的时候换成那一项的公式；绕成圈报 `formula.cycle`。脚本的变量不能和设置项同名（`script.setting_name`）。
- 有哪些项、值是什么类型在 `rules/skillconfig.py`；公式不能掷骰。
- 范围形状：`sphere(radius=)`、`cone(length=, angle=)`、`capsule(length=, width=)`、`box(length=, width=, height=)`，参数是数字（米、度）。分组要允许这种形状。
- 设置物：`placement(radius=, perceive=, charges=, duration=, notify=)`，radius 必填；duration 按分钟。分组要打开“可以是设置物”。
- `cast_time`、`cooldown` 要分组打开“有施放时间和冷却时间”。
- 设置物（陷阱、结界）在 KP 裁定放下时检查：`range` 是放置点离设置者的距离，`visible` 是放置点要在设置者的视线内，`requires` 和冷却照样检查，放下后开始冷却；`noise` 范围内的其他玩家在发布时察觉到。
- `cast_time` 在解析玩家行动时算（那时还不知道这次填多少），“使用时填写”的列按下限算。
- 引擎怎么用：KP 声明使用时，引擎按 `target` 定对象（self / none 时不看 KP 给的对象，single 不给对象就拒绝），检查 `requires`、`range`（按地图距离）、`visible`（按感知），不满足就拒绝（`use.requires`、`use.out_of_range`、`use.not_perceived`）；`noise` 范围内其他玩家在回合发布时收到一条 `entry_noticed`（看得见使用者的还知道是谁）。

---

### 检定和应对

技能设置里和“打没打中”有关的三项：

```
check = "magic_attack"        # 施法者做的检定；None / True 是不掷骰、必中（默认）
reactions = ["dodge"]          # 写了就可以被应对
difficulty = 10                # 没人对抗时的难度
```

- 打没打中全由引擎决定，KP 不判。成功或大成功算命中，没命中只扣消耗、开始冷却，不执行效果。
- `reactions` 写了、对象是玩家：KP 声明使用后回合停下等他（没有时限），他从这些里选一个：`reactions` 里的检定（和施法者的检定对抗）、自己能当反应的技能（所在分组打开了“可以当反应”、瞬发、不在冷却；消耗、冷却照算）、不抵抗。同一轮里打在他身上的攻击攒成一次问。对象是 NPC：引擎替它挑最有利的检定。
- 选了技能当反应：先算这个技能（它的 `check` 和施法者的点数比，它的效果先执行），效果里写了 `self.negate()` 的话这次攻击作废；否则再按对抗判命中、执行攻击的效果。
- 技能脚本里：`result` 是这次检定的结果（`critical_success`、`success`、`failure`、`critical_failure`，没有检定时是空）；`reacting` 是这次是不是当反应用的。

### 检定的代码

规则包的每个检定也是一段 `名字 = 值`（`rules/checkconfig.py`）：

```
label = "感知检定"
dice = 1d20 + per              # 在做检定的角色身上算
target = 0                     # 目标值，用不到就是 0
critical_success = natural == 20
critical_failure = natural == 1
success = roll > difficulty
opposed_by = "perception"      # 对抗时对方掷什么；None 是同一个检定
```

- 结果固定四个，按顺序判断：大成功、大失败、成功，第一条成立的就是结果，都不成立是失败。
- 条件里能用：`roll`（总点数）、`natural`（骰子本身的点数）、`target`、`difficulty`（KP 给的难度；对抗时是对方掷出的点数，所以 `roll > difficulty` 两种情况都能用）、`opp_roll`、`opp_target`。

---

## 四、名字指什么

名字的写法是 `字母或下划线开头，后面跟字母、数字、下划线`，可以用 `.` 连起来。中文也算字母，但规则包里建议用英文。名字的含义由 `rules` 决定：

| 写法 | 含义 |
| --- | --- |
| `str` | 自己的字段、推导值，或规则包的命名公式 |
| `self.str` | 同上，显式写“自己的” |
| `this.level` | 条目里（修正、技能脚本、施放时间、冷却、使用时填写的上下限、设置物参数……）指这一条自己的列，包括这次使用时填写的数 |
| `this.damage` | 如果 `damage` 是掷骰公式列，就展开成那一列里写的公式，再参与计算（能掷骰的地方当场掷）。公式列可以引用别的公式列，绕成圈报 `formula.cycle` |
| `companion.str` | `<模板>.x`：自己这边的角色。写自己的模板名就是自己；写别的模板名，是同一个玩家控制的那个模板的角色。没有这种角色按 0 算，有不止一个报错 |
| `hero.fireball` | `<模板>.<条目ID>`：有没有这一条（1 / 0） |
| `hero.fireball.level` | `<模板>.<条目ID>.<列>`：那一条的某一列；没有这一条按 0 算；“使用时填写”的列不能引用 |
| `target.hp` | 技能的对象的值（只在使用技能时有） |
| `target.template`、`self.template`、`<模板>.template` | 那个角色的模板名（文字），例如 `2 if target.template == "monster" else 1` |
| `roll`、`target`、`difficulty`、`opp_roll`、`opp_target` | 只在检定的结果条件里有 |

字段名不能叫 `d`、`d6` 这种会被当成掷骰的名字。条目 ID 不能叫 `self`、`this`、`target`、`template`。字段、推导值、分组、模板、条目 ID 都不能用 Python 的关键字（`if`、`and`、`class`、`pass`、`in`……）。

---

## 五、出错代码

解析和校验的问题用代码报给前端，前端翻译成说明（翻译在 `scripts/i18n_source.py` 的 `codes.*`）。技能脚本的问题都带 `line`（第几行）。Python 的语法错误换成下面的代码。

| 代码 | 什么时候 |
| --- | --- |
| `formula.empty` | 空的 |
| `formula.syntax` | 别的语法错（Python 读不了） |
| `formula.unclosed` / `formula.unmatched` / `formula.unclosed_string` | 括号没关上 / 多了右括号 / 引号没关上 |
| `formula.single_equals` | 比较相等写成了单个 `=` |
| `formula.if_call` / `script.if_call` | 把 `if` 当函数写成了 `if(条件, a, b)`；提示改成 `a if 条件 else b`，或者脚本里的 `if 条件:` 块 |
| `formula.unsupported` | Python 的写法，但不在白名单里 |
| `formula.chained_comparison` | 连写的比较中间那一项掷骰（会掷两次） |
| `formula.unknown_function` / `formula.arity` | 没有这个函数 / 参数个数不对 |
| `formula.unknown_name` / `formula.dice_needs_space` | 没有这个名字 / 像是两个名字之间掷骰（`strdper`），提示写 `dice(str, per)` |
| `formula.dice_not_allowed` / `formula.dice_range` | 这里不能掷骰 / 骰子个数或面数超范围 |
| `formula.text_in_arithmetic` / `formula.text_result` | 文字参与计算 / 结果是文字但这里要数字 |
| `formula.division_by_zero` / `formula.math_domain` | 除以 0 / 算不出结果（例如负数开平方） |
| `formula.cycle` | 循环引用 |
| `formula.list_ref` / `formula.unknown_group` | `count` / `sum` 的第一个参数不是分组引用 / 没有这个分组或列 |
| `formula.this_outside_entry` | 不在条目里却写了 `this.x` |
| `script.bad_statement` | 不是 `对象.动作(参数)`、`if`、`pass` |
| `script.bad_variable` / `script.setting_name` | 局部变量起名叫了 `self` / `target` / `this` / 和技能设置的项同名 |
| `script.unknown_receiver` / `script.unknown_verb` | 对象不是 `self` / `target`；没有这个动作 |
| `script.arity` / `script.field_arg` | 参数个数不对 / 字段参数不是一个简单的名字 |
| `script.unexpected_indent` | 缩进不对：同一段没对齐，或不在 `if` / `elif` / `else` 下面却缩进了 |
| `script.empty_block` | `if` / `elif` / `else` 下面没有缩进的行（空着就写 `pass`） |
| `config.bad_line` / `config.duplicate` / `config.unknown_key` | 技能设置：不是 `名字 = 值` / 写了两次 / 没有这一项 |
| `config.bad_value` / `config.bad_call` / `config.bad_arg` / `config.missing_arg` / `config.call_keywords` | 技能设置：值的类型不对 / 构造的名字不对 / 参数不对 / 少了参数 / 参数没写成 `名字=值` |
| `script.not_runtime` / `script.not_derived` | `add` / `sub` / `set` 的字段不是运行值；`modify` 的不是推导值 |

---

## 六、给开发者

- `parse(text)` → 公式树（`Num`、`Str`、`Name`、`Unary`、`Binary`、`Call`、`Dice`），出错抛 `FormulaError(code, **params)`。解析结果有缓存。
  - 过程：`desugar` 把 `3d6` 这类写法改成 `dice(3, 6)` → `ast.parse(mode="eval")` → `convert` 按白名单把 Python 的树换成公式树。
  - `a if c else b`、`and`、`or`、`not` 换成内部的 `Call("if" / "and" / "or" / "not")`；`%`、`**`、`//` 换成 `mod`、`pow`、`floor(a / b)`；连写的比较换成 `and`。
  - 求值和公式树与 Python 无关，只有解析这一步借用 Python。
- `evaluate(node, resolve, lookup, faces=None, collect=None)`：`resolve` 解析名字，`lookup` 查表，`faces` 掷骰（不给就不能掷），`collect` 给 `count` / `sum` 列出分组的值。
- `names` / `tables` / `lists`：公式里引用的名字、表、分组；`has_dice`：有没有掷骰。
- `substitute(node, fn)`：把名字换成别的公式树（`this.<掷骰公式列>` 的展开用它）。`to_text(node, values)`：写回能被 `parse` 读回来的文本，并把一些名字换成值（冻结用它）。
- `parse_script(text)` → `ScriptNode`（`Statement` 或 `If`）的元组，用 `ast.parse(mode="exec")`。`Statement`：行号、对象、动作和参数（写成 `to_text` 的文本）。`If`：一串 `Branch`（行号、条件原文或 `None`、分支里的语句）。`statements(nodes)` 列出所有分支里的动作句。
- `parse_config(text)` → `Setting` 的元组：行号、名字、值的公式文本；构造（`sphere(radius=5)`）时是构造名和各参数的公式文本。
- 改语法时，同时改：这份说明、前端“公式速查”（`frontend/src/ui/FormulaHelp.tsx`，函数表有测试保证和 `FUNCTIONS` 一致）、`tests/lang`。存下来的公式要跟着改写法时加一个迁移（参考 `web/migrations/versions/0005_python_syntax.py`：旧解析器读、`to_text` 写）。
