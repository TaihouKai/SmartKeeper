{{common}}

任务：检定规划。下面是本轮全部行动和裁定需要的上下文，但还没有掷骰和空间查询的结果。你要声明为了裁定本轮需要哪些检定和空间查询，由引擎执行：
- 命名检定：{"entity": "<实体 id>", "check": "<规则包里的检定名>", "against": 难度数值 或 "<对抗方实体 id>" 或 null, "reason": "..."}
- 规则包没有覆盖的情况用临时检定：{"entity": "<实体 id>", "adhoc": {"dice": "1d100", "target": 50, "success_when": "roll<=target" 或 "roll>=target"}, "reason": "..."}
- 空间查询（LLM 不做空间推理，距离、视线、范围命中都交给引擎）：
  - {"query_id": "q1", "kind": "within", "center": {"kind": "entity", "id": "<实体 id>"}, "radius": 米}
  - {"query_id": "q2", "kind": "sweep", "entity": "<发动者实体 id>", "ability": "<角色卡上的能力名>", "toward": {"kind": "entity", "id": "..."}}
    能力的形状和尺寸取自角色卡，你只给朝向。能力只有文字描述、没有结构化形状时，另给 "shape": {"kind": "capsule|box|sphere|cone", "length": 米, "width": 米, "height": 米, "radius": 米, "angle": 度}
  - {"query_id": "q3", "kind": "line_of_sight", "a": {"kind": "entity", "id": "..."}, "b": {"kind": "entity", "id": "..."}}
  - {"query_id": "q4", "kind": "distance", "a": ..., "b": ...}
  toward / center / a / b 也可以是 {"kind": "feature", "id": "<地物 id>"} 或 {"kind": "point", "point": {"x": 0, "y": 0, "z": 0}}
- 不需要检定的行动就不要声明检定。query_id 在本轮内唯一。

只输出一个 JSON 对象：{"checks": [...], "queries": [...]}
