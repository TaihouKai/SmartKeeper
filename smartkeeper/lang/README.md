# `lang`：公式与技能脚本

规则包里所有能算的东西都用这门小语言写：推导值、上下限、检定的骰子和目标值、条目的修正、施放时间和冷却时间、技能脚本。
引擎不执行任何外部代码，这里是自己的解析器和求值器。

- 依赖：无。这个包不认识角色卡和规则包；名字指什么、表怎么查、骰子怎么掷，都由调用方（`rules`）以回调传进来。
- 文件：`formula.py` 是公式，`script.py` 是技能脚本。
- 单独测试：`uv run pytest tests/lang`

下面先讲公式，再讲技能脚本，最后是名字的含义（由 `rules` 决定）和出错代码。

---

## 一、公式

一条公式算出一个值：数字，或一段文字。

### 1. 字面量

| 写法 | 说明 |
| --- | --- |
| `3`、`2.5` | 数字。没有负数字面量，`-3` 是对 3 取负 |
| `"warrior"` | 文字，用英文双引号；里面不能再有双引号 |

### 2. 运算

按优先级从高到低：

| 优先级 | 运算 | 说明 |
| --- | --- | --- |
| 1 | `( … )`、函数调用、名字、字面量 | |
| 2 | `NdM` | 掷骰，比乘除先算：`2d6 * 5` 是 `(2d6) * 5` |
| 3 | `-x` | 取负 |
| 4 | `*`、`/` | 除以 0 报错 |
| 5 | `+`、`-` | |
| 6 | `<` `<=` `>` `>=` `==` `!=` | 成立得 1，不成立得 0；单个 `=` 等同 `==`；不能连写（`1 < x < 3` 报错，用 `and(1 < x, x < 3)`） |

- 同级从左往右算。
- 文字只能用 `==` / `!=` 比较，参与加减乘除会报错。
- 真假：0 和空文字是假，其余是真。

### 3. 掷骰

| 写法 | 含义 |
| --- | --- |
| `3d6` | 3 颗 6 面骰求和 |
| `d20`、`d%` | 省略个数就是 1 颗；`d%` 是 `d100` |
| `1dstr`、`2d(str + 1)` | 数字后面紧跟 `d`，面数可以是名字或括号 |
| `level d luck` | 两个名字之间掷骰，`d` 两边要加空格（`leveldluck` 会被当成一个名字） |
| `highest(4, 6, 3)` | 掷 4 颗 6 面骰，取最高的 3 颗之和；`lowest` 取最低的 |

- 个数和面数先四舍五入（.5 远离零）。个数 0～1000，面数 1～100000，超出报错。
- **只有能掷骰的地方才能掷骰**：检定的骰子、KP 的临时检定和自由掷骰、技能脚本的数量和分钟、掷骰公式列。
- 推导值、上下限、初值、每分钟变化、检定目标值和结果条件、施放时间、冷却时间、`modify` 的新值公式，每次查看或每轮都要重新算，所以不能掷骰。写了会报 `formula.dice_not_allowed`。

### 4. 函数

| 函数 | 说明 |
| --- | --- |
| `abs(x)` `floor(x)` `ceil(x)` `trunc(x)` `sign(x)` `sqrt(x)` | 绝对值、向下取整、向上取整、向零取整、符号（1 / -1 / 0）、平方根 |
| `round(x)` | 四舍五入，.5 远离零（不是银行家舍入） |
| `pow(x, y)` | x 的 y 次方 |
| `mod(x, y)` | 余数，和 y 同号：`mod(-1, 3)` 是 2 |
| `min(a, b, …)` `max(a, b, …)` | 最小、最大 |
| `clamp(x, lo, hi)` | 把 x 限制在 lo..hi |
| `if(cond, a, b)` | 条件为真取 a，否则取 b；没选中的一边不算（不会掷骰、不会报错） |
| `and(a, …)` `or(a, …)` `not(a)` | 逻辑运算，结果 1 / 0；`and`、`or` 短路 |
| `lookup(表, key)` | 查规则包的表。范围表取“不超过 key 的最大一行”，精确表要求完全相等 |
| `count(分组)` | 分组里有几条 |
| `count(分组.列, 值)` | 这一列等于这个值的有几条（数字或文字都行） |
| `sum(分组.列)` | 这一列加起来是多少 |
| `highest(n, s, k)` `lowest(n, s, k)` | 掷骰，见上 |

- `lookup` 的第一个参数是表名，`count` / `sum` 的第一个参数是分组引用，它们都不是普通名字。
- 分组前面可以加 `<模板>.` 或 `target.`，例如 `count(companion.traits.rank, 3)`。
- `count` / `sum` 统计时跳过没填的列；“使用时填写”的列不能统计。

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

- 一行一句，也可以用 `;` 隔开。
- `#` 到行尾是注释（双引号里的 `#` 不算）。
- 括号没关上时，换行算同一句。
- 空行和只有注释的行忽略；整段为空表示没有脚本。

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

- 写法和 Python 一样：`if 条件:`，下面缩进的几行是这一支；后面可以接任意个 `elif 条件:`，最后可以有一个 `else:`。
- 从上往下，第一个成立的条件那一支执行，其余跳过；都不成立就执行 `else`（没有 `else` 就什么都不做）。
- 缩进几个空格都行（Tab 算 4 个），但同一支里的行要对齐。分支里可以再套分支。
- `if` 后面的条件是一条公式，0 和空文字算不成立。
- 条件在声明使用时算，**不能掷骰**，因为条件掷出来的点数没有地方记进日志。要按概率触发，就把掷骰放进数量里，例如 `target.damage(if(1d100 <= 30, 10, 0))`。
- 没有对象时，条件里用到 `target.` 的整个 `if … elif … else` 都跳过。
- 编辑框里按 Tab 插入 4 个空格；回车会保持这一行的缩进，行尾是冒号时再多缩进一级。

### 4. 求值时机

1. **KP 规划时声明使用：** 引擎立刻把每一句算好，条件也在这时判断。数量和分钟当场掷骰，点数记进 `entry_used` 事件。`modify` 的新值公式会被“冻结”：除了被修正的推导值自己的名字，其余名字都换成此刻的值。
   - 例如使用者 `str` 是 12，`target.modify(move_speed, move_speed + str, 10)` 存成 `(move_speed + 12)`。之后在带着这条修正的角色身上，用他当时的 `move_speed` 算。
2. **KP 裁定生效：** 引擎照着算好的数值，一句一句执行。没生效（没打中、被挡住）的话只扣使用时的消耗，冷却照样开始。
3. 分钟换算成游戏内秒。施放时间、冷却时间和脚本里的持续时间都按分钟。

---

## 三、名字指什么

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
| `target.template`、`self.template`、`<模板>.template` | 那个角色的模板名（文字），例如 `if(target.template == "monster", 2, 1)` |
| `roll`、`target`、`difficulty`、`opp_roll`、`opp_target` | 只在检定的结果条件里有 |

字段名不能叫 `d`、`d6` 这种会被当成掷骰的名字。条目 ID 不能叫 `self`、`this`、`target`、`template`。

---

## 四、出错代码

解析和校验的问题用代码报给前端，前端翻译成说明（翻译在 `scripts/i18n_source.py` 的 `codes.*`）。技能脚本的问题都带 `line`（第几行）。

| 代码 | 什么时候 |
| --- | --- |
| `formula.empty` / `formula.bad_token` / `formula.unexpected` / `formula.unexpected_end` / `formula.trailing` / `formula.expected` | 语法错 |
| `formula.chained_comparison` | 比较连写 |
| `formula.unknown_function` / `formula.arity` | 没有这个函数 / 参数个数不对 |
| `formula.unknown_name` / `formula.dice_needs_space` | 没有这个名字 / 像是两个名字之间掷骰忘了加空格 |
| `formula.dice_not_allowed` / `formula.dice_range` | 这里不能掷骰 / 骰子个数或面数超范围 |
| `formula.text_in_arithmetic` / `formula.text_result` | 文字参与计算 / 结果是文字但这里要数字 |
| `formula.division_by_zero` / `formula.math_domain` | 除以 0 / 算不出结果（例如负数开平方） |
| `formula.cycle` | 循环引用 |
| `formula.list_ref` / `formula.unknown_group` | `count` / `sum` 的第一个参数不是分组引用 / 没有这个分组或列 |
| `formula.this_outside_entry` | 不在条目里却写了 `this.x` |
| `script.bad_statement` | 不是 `对象.动作(参数)` 的形式 |
| `script.unknown_receiver` / `script.unknown_verb` | 对象不是 `self` / `target`；没有这个动作 |
| `script.arity` / `script.field_arg` | 参数个数不对 / 字段参数不是一个简单的名字 |
| `script.unexpected_indent` | 缩进不对：同一段没对齐，或不在 `if` / `elif` / `else` 下面却缩进了 |
| `script.empty_block` | `if` / `elif` / `else` 下面没有缩进的行 |
| `script.dangling_else` | `elif` / `else` 前面没有对齐的 `if` |
| `script.bad_condition` | `if` / `elif` 后面没写条件 |
| `script.not_runtime` / `script.not_derived` | `add` / `sub` / `set` 的字段不是运行值；`modify` 的不是推导值 |

---

## 五、给开发者

- `parse(text)` → 公式树（`Num`、`Str`、`Name`、`Unary`、`Binary`、`Call`、`Dice`），出错抛 `FormulaError(code, **params)`。解析结果有缓存。
- `evaluate(node, resolve, lookup, faces=None, collect=None)`：`resolve` 解析名字，`lookup` 查表，`faces` 掷骰（不给就不能掷），`collect` 给 `count` / `sum` 列出分组的值。
- `names` / `tables` / `lists`：公式里引用的名字、表、分组；`has_dice`：有没有掷骰。
- `substitute(node, fn)`：把名字换成别的公式树（`this.<掷骰公式列>` 的展开用它）。`to_text(node, values)`：写回文本，并把一些名字换成值（冻结用它）。
- `parse_script(text)` → `ScriptNode`（`Statement` 或 `If`）的元组。`Statement`：行号、对象、动作和参数原文（参数已经检查过能解析）。`If`：一串 `Branch`（行号、条件原文或 `None`、分支里的语句）。`statements(nodes)` 列出所有分支里的动作句。
- 改语法时，同时改：这份说明、前端“公式速查”（`frontend/src/ui/FormulaHelp.tsx`，函数表有测试保证和 `FUNCTIONS` 一致）、`tests/lang`。
