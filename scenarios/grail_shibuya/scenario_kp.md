---
# 开场时就有名字的地点：所有玩家的地图上都显示，消息里提到时可以点
places:
  - {name: 教会, at: {place: bldg_155749494}}      # 宫下公园东边的矮楼
  - {name: 宫下公园, at: {place: lm_9855737969}}
npcs:
  - id: npc_kurokawa
    template: master
    sheet:
      name: 黑川冬弥
      fields:
        appearance: 三十岁上下的男人，深灰色大衣，戴着金丝边眼镜，左手总是插在口袋里
        background: 魔术师
        can_fly: false
        str: 0
        agi: 1
        con: 1
        int: 5
        per: 3
        cha: 1
        mp_mult: 4
        weapon_db: 0
        weapon_mystic: false
    location: {place: セルリアンタワー, floor: 30}
  - id: npc_lancer
    template: servant
    sheet:
      name: 赵云（常山赵子龙）
      alias: Lancer
      fields:
        appearance: 银白色铠甲的高大青年，手持一杆亮银长枪，枪缨是白色的
        legend: 三国时代蜀汉的名将，常山真定人。长坂坡单骑救主，在曹军中七进七出。
        weapons: 一杆亮银枪，枪法以快和变化著称，民间传说中有“七探盘蛇枪”。
        weakness: 一生谨守本分，面对主君的不义命令会动摇。
        manner: 寡言，谨慎守礼，忠义无双。
        can_fly: false
        klass: Lancer
        str: 4
        agi: 5
        con: 4
        int: 2
        luk: 4
        np: 4
        spirit_form: true
      preset_fields:
        klass_skill:
          对魔力: {level: 3}
      groups:
        noble_phantasm:
          - name: 七探盘蛇
            description: 传说中赵云的枪法：一枪七探，如盘蛇般缠住对手的要害。
            fields: {level: 4, np_type: 对人, plus: 0}
            config: ""
            uses:
              - name: 当作武器
                description: 不解放真名，只用枪术。
                config: |
                  target = "single"
                  range = 3
                  visible = True
                  noise = 30
                  requires = not spirit_form
                  check = best("strength", "agility")
                  reactions = ["counter", "dodge"]
                  hit = level >= 1 and level >= opp_level
                script: |
                  half = opposed and level == opp_level
                  target.damage(dice(str, lookup(class_melee, klass)) / (2 if half else 1))
              - name: 真名解放·对人
                description: 解放真名，七道枪影同时刺向一个人，只能闪避。
                config: |
                  target = "single"
                  visible = True
                  noise = 1000
                  requires = this.release and not spirit_form and mp >= cost
                  reactions = ["dodge"]
                  auto_level = 3 if distance <= 100 else 2
                script: |
                  cost = lookup(skill_cost, this.level) * lookup(np_cost, this.np_type)
                  target.damage(dice(lookup(np_dice_count, this.level), lookup(np_dice_sides, this.level)) + lookup(np_bonus, this.level))
    location: {place: セルリアンタワー, floor: 30}
  - id: npc_father
    template: master
    sheet:
      name: 神父·朝仓
      fields:
        appearance: 穿黑色神父服的中年人，笑容温和，手里总拿着一本旧圣经
        background: 代行者
        can_fly: false
        str: 3
        agi: 2
        con: 3
        int: 2
        per: 3
        cha: 4
        mp_mult: 2
        weapon_db: 6
        weapon_mystic: true
    location: {place: MIYASHITA PARK South}
---
# KP 专属

## 真相

- 监督者神父·朝仓（npc_father）表面上中立，暗中和 Lancer 的御主黑川冬弥（npc_kurokawa）结了盟：他会把来登记的御主的情报（人数、住处、英灵的职阶）告诉黑川。
- 黑川是时钟塔出身、被逐出门墙的魔术师，在塞鲁利安塔（セルリアンタワー）三十层布置了魔术工房。他的计划是午夜零点一过，就让 Lancer 在涩谷十字路口伏击第一组离开教会的御主。
- Lancer 的真名是赵云。他忠于御主，但厌恶偷袭和对普通人下手；如果黑川命令他杀普通人，他会犹豫，黑川可能为此动用令咒。
- 黑川上个月杀了一个发现他和神父勾结的本地魔术师。如果有玩家的背景和本地魔术世家、或者和这个死者有关，可以把死者写成他的亲人或师长，作为他的个人线索。

## NPC

- 黑川冬弥：冷静、傲慢，看不起“没有传承的魔术师”和普通人。不会亲自上前线，用使魔监视战场。
- Lancer（赵云）：寡言，重礼节，战斗时先报职阶（不报真名）。被逼到绝境或者为了保护御主，才会解放真名。
  - 线索（由浅到深，按玩家的观察和学识给）：银白色的中式铠甲和长枪 → 枪法快、变化多，像中国武将 → 救人时奋不顾身、单骑冲阵 → 枪招里有“盘蛇”的影子 → 赵云。
- 神父·朝仓：和蔼可亲，热心地给每个人讲圣杯战争的规矩，打听每个御主的英灵是什么职阶。

## 开场

- 没有固定的开场身份，玩家自己写背景。开场时按背景给每组御主和英灵安排起点，例如：
  - 外来的魔术师：道玄坂一带的酒店（渋谷エクセルホテル東急）。
  - 本地人或本地魔术世家：自家或道玄坂センタービル一带。
  - 卷入的普通人：宫下公园附近（MIYASHITA PARK South），离教会最近。
  - 教会相关：Shibuya 109 一带，或者直接在教会。
- 英灵和御主放在一起；英灵默认灵体化。
- 背景里写到的、和剧本有关的东西（仇人、师承、圣遗物的来历），尽量接到剧本的线索上。

## 推进

1. 23:00～24:00：玩家各自出发去教会登记，可能在路上相遇。神父在宫下公园旁迎接每一个人，套他们的话。
2. 零点：战争开始。Lancer 在十字路口（Watch Shibuya Crossing 一带）出现，挑战第一组经过的御主。黑川的使魔在楼顶看着。
3. 之后：玩家可以追查使魔、跟踪 Lancer 撤退的方向找到塞鲁利安塔，或者回头质问神父。

## 结局条件

- 第一夜活下来：好结局（之后的夜晚可以接着跑）。
- 查出神父和黑川的勾结：额外收获。
- 听到 Lancer 解放真名、或者从传说推断出他是赵云：玩家知道他的弱点和战法。
- 任何一名御主死亡：那名玩家的英灵开始消散，可以去找别的御主缔结契约。
