{{common}}

任务：检定规划。下面是本轮全部行动和裁定需要的上下文，但还没有掷骰和空间查询的结果。你要声明为了裁定本轮需要哪些检定和空间查询，由引擎执行：
- 命名检定：{"entity": "<实体 id>", "check": "<规则包里的检定名>", "against": 难度数值 或 "<对抗方实体 id>" 或 null, "reason": "..."}
- 规则包没有覆盖的情况用临时检定：{"entity": "<实体 id>", "adhoc": {"dice": "1d100", "target": 50, "success_when": "roll<=target" 或 "roll>=target"}, "reason": "..."}
- 掷骰公式：角色卡上类型为“掷骰公式”的字段（例如技能的伤害 damage = 1d str），用到时由引擎掷：{"entity": "<实体 id>", "entry": "<条目名，例如技能名>" 或 null（模板本身的字段）, "field": "<字段名>", "params": {"<使用时填写的列名>": 数值}, "reason": "..."}。伤害、治疗这类数值一律这样掷，不要自己编数字。
  条目所在分组有“使用时填写”（param）的列时（例如这次消耗多少魔力），params 里必须给出每一列的数：按玩家行动里说的；玩家没说就用规则允许的最小值。超出范围或资源不够时引擎不掷，裁定时就没有这个结果。消耗的资源由引擎在结算时自动扣，不要再在 state_patch 里扣。
- 技能使用：角色对某人（或自己）用了一个带技能脚本的技能时声明：{"source": "<施法者实体 id>", "entry": "<技能名或 ID>", "target": "<对象实体 id>，对自己用就写施法者自己的 id" 或 null, "params": {"<使用时填写的列名>": 数值}, "reason": "..."}。状态里有 dead（已死亡）的角色不能用技能；有 cooldown:<技能名> 的表示那个技能还在冷却，不能用。技能对谁用由玩家决定（攻击技能也可以对自己用），脚本里写 target 的部分落在 target 身上，写 self 的部分落在施法者身上。技能的设置由引擎执行，不用你判断：只能对自己用或没有对象的技能，引擎自己定对象；要选对象的技能不给 target 会被拒绝；射程、对象要在施法者感知里、使用条件不满足时引擎拒绝这次使用（错误代码 use.out_of_range、use.not_perceived、use.requires），这时按规则让行动失败或改成别的行动，不要绕过；技能的动静由引擎通知附近的玩家。引擎会算好伤害、治疗、增减的数值。技能设置里有检定（check）的技能，打没打中由引擎在声明时就掷骰判定（对象是玩家的话由他自己选怎么应对，引擎会等他；NPC 由引擎替它选），不要再为它声明检定；所有技能打没打中都由引擎决定；没有检定的技能，生效与否你在裁定时决定，命中要靠检定的同时声明对应的命名检定。命名检定的结果是四个等级之一：critical_success、success、failure、critical_failure。
- 空间查询（LLM 不做空间推理，距离、视线、范围命中都交给引擎）：
  - {"query_id": "q1", "kind": "within", "center": {"kind": "entity", "id": "<实体 id>"}, "radius": 米}
  - {"query_id": "q2", "kind": "sweep", "entity": "<发动者实体 id>", "ability": "<角色卡上的能力名>", "toward": {"kind": "entity", "id": "..."}}
    能力的形状和尺寸取自角色卡，你只给朝向。能力只有文字描述、没有结构化形状时，另给 "shape": {"kind": "capsule|box|sphere|cone", "length": 米, "width": 米, "height": 米, "radius": 米, "angle": 度}
  - {"query_id": "q3", "kind": "line_of_sight", "a": {"kind": "entity", "id": "..."}, "b": {"kind": "entity", "id": "..."}}
  - {"query_id": "q4", "kind": "distance", "a": ..., "b": ...}
  toward / center / a / b 也可以是 {"kind": "feature", "id": "<地物 id>"} 或 {"kind": "point", "point": {"x": 0, "y": 0, "z": 0}}
- 不需要检定的行动就不要声明检定。query_id 在本轮内唯一。

只输出一个 JSON 对象：{"checks": [...], "rolls": [...], "uses": [...], "queries": [...]}
