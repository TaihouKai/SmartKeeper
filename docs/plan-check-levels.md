# 计划：按成功等级对抗（暂缓，等英灵模板写完再做）

状态：设计已和本人对过，**还没实现**。御主和英灵两边的模板都写好以后再做，那时两边都能测。

## 为什么要做

规则书的近战（反击、闪避）是“双方各自算成功等级，再比等级”，现在的检定只有“比点数”，写不出来。现在缺的：

| 规则 | 现在的问题 |
| --- | --- |
| 比较双方的成功等级 | 条件里只有双方点数，没有双方各自的等级（也没有对方的 `natural`） |
| 平手时攻击方只造成一半伤害 | 技能脚本不知道是不是平手 |
| 攻击方同时掷筋力和敏捷，取等级高的 | 一个技能只能做一个检定 |
| 应对只能用技能（反击、闪避） | 想让对象能应对，`reactions` 里必须列检定 |

## 要加的四样

1. `level` / `opp_level`：双方各自按自己的检定算出的成功等级，数字：3 大成功、2 成功、1 失败、0 大失败。技能的 `hit` 条件和技能脚本里都能用。（应对技能的检定要和攻击方的检定互为对手，双方的 `opp_target`、`opp_level` 都算好。）
2. 技能设置 `hit`：被对抗时的命中条件；不写时按现在的“成功就命中”。
3. `check = best("strength", "agility")`：几个检定都掷，取等级高的那个。
4. `reactions = True`：可以被应对，但只用技能应对（不给检定选项）。

## 写完以后，规则书里两条的写法（用来验收）

检定（各模板定义 `strength_mod`、`agility_mod`）：

```
# strength
label = "筋力"
dice = 1d20 + strength_mod
critical_success = natural >= 19
critical_failure = natural <= 2
success = roll > 10
```

```
# agility
label = "敏捷"
dice = 1d20 + agility_mod
critical_success = natural >= 19
critical_failure = natural <= 2
success = roll > 10
```

技能「近战攻击」：

```
# 设置
check = best("strength", "agility")
reactions = True
hit = level >= 2 and level >= opp_level      # 自己成功、等级不低于对方；平手算命中

# 效果
dmg = this.damage
target.damage(dmg / 2 if level == opp_level else dmg)   # 平手只造成一半
```

应对技能「反击」：

```
# 设置
check = "strength"

# 效果
if reacting and level >= 2 and level > opp_level:
    self.negate()
    target.damage(this.damage)     # 应对技能里的 target 是攻击者
```

应对技能「闪避」：

```
# 设置
check = "agility"

# 效果
if reacting and level >= 2 and level >= opp_level:
    self.negate()                  # 平手也算闪开
```

验收用例（写进测试）：

| 情况 | 期望 |
| --- | --- |
| 反击，攻击方等级高 | 攻击命中，全额伤害 |
| 反击，被攻击方等级高 | 攻击作废，攻击方受到反击伤害 |
| 反击，平手 | 攻击命中，伤害减半，没有反击 |
| 闪避，攻击方等级高 | 攻击命中 |
| 闪避，平手或被攻击方高 | 攻击作废 |
| 双方都失败 | 无事发生 |

## 待定

- 等级只有四档。规则书如果还有“困难成功”“极难成功”这类档位，要扩展等级（到时再看规则书）。
