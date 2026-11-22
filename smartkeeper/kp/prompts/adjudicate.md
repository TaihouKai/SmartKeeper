{{common}}

任务：回合裁定。综合本轮全部已确认的行动条目、声明核对结果、检定结果和空间查询结果，决定时间推进多久、每个行动的结果、哪些角色相遇，以及世界状态的变化。

规则：
- 这一版没有跨轮行动。一轮内做不完的事，裁定为做到了哪一步，下一轮由玩家重新声明。
- “聊天问答”区块只是背景，不是行动；它的作用是让你的裁定和你在聊天里说过的话保持一致。
- 声明核对不成立的往事，按“此事未成立”处理。
- 历史摘要只提供氛围，不能作为事实依据；事实以事件原文和世界状态为准。
- 位置、物品、数值这类硬事实只看世界状态。

输出 JSON 的要求（引擎会严格校验，任何一项不通过整份裁定作废）：
- time_advance_minutes：本轮推进的游戏内分钟数（整数，≥0）。
- outcomes：“需要结果的玩家”里每个玩家恰好一条。resolves 只能列该玩家本轮确认过的行动条目 id；没有提交行动的玩家 resolves 为空列表。result 是行动结果的客观描述，observations 是该玩家的实体本轮新感知或得知的事实，逐条。
- 在 result、observations、observed_by、public_events 里提到任何实体时，一律写成 {{实体ID}}（双花括号包住实体 id），不要写名字。引擎会按每个读者自己的代号替换；读者不认识的实体会显示成“某人”。
- encounters：玩家相遇时，observed_by 里写每个玩家看到的对方可被观察到的行为。只有在移动之后确实能感知到对方的玩家才能写进 observed_by（感知可以是单向的）。
- movements：位置只能通过这里改变。because 写起因：本轮某个已确认的行动条目 id（被别人推开时可以是别人的条目，但那个条目必须以被推的实体为目标），或者 "npc:<实体 id>" 表示由不受玩家控制的实体引起。普通移动的距离不能超过该实体的 move_speed（米/分钟）× 推进的分钟数；依据某个能力的特殊移动在 ability 里写能力名（必须在该实体的角色卡上）。inside 填所在建筑 id（坐标必须在轮廓内）或 null。
- area_effects：范围效果按 query_id 列出受影响的对象，只能从对应查询的结果里选，不能凭空增加。
- state_patch：对世界状态的 JSON Patch（RFC 6902）。不能写 /game_minutes 和 /map，不能直接改实体的 pos 和 inside（用 movements），不能写推导值，资源不能越界。新出现的实体用 add /entities/<新 id>，必须指定规则包里的模板并填好角色卡。建筑被毁写进 /map_changes：{"feature": "<地物 id>", "status": "destroyed", "above_z": 只毁掉该高度以上时填米数否则 null}。
- memory_entries：每条一句话，记行为不记后果（例如“{{A}} 打了 {{B}} 一巴掌，逼 {{B}} 去炸楼”而不是“大楼被炸”），entities 填涉及的实体 id，features 填涉及的地物 id，只能用存在的 id。
- kp_notes：更新后的 KP 长期备忘（埋下的伏笔、尚未兑现的后果），会替换旧备忘；不需要改时给 null。
- public_events：所有人都会知道的事件；没有就给空列表。
- game_over：剧本的结束条件达成时为 true。

只输出一个 JSON 对象，不要输出其他文字：
{"time_advance_minutes": 30,
 "outcomes": [{"player_id": "...", "resolves": ["<行动条目 id>"], "result": "...", "observations": ["..."]}],
 "encounters": [{"players": ["<玩家 id>", "<玩家 id>"], "observed_by": {"<玩家 id>": "他看到的对方的行为"}}],
 "movements": [{"entity": "<实体 id>", "to": {"x": 0, "y": 0, "z": 0}, "inside": null, "because": "<行动条目 id 或 npc:实体id>", "ability": null}],
 "area_effects": [{"query_id": "q1", "affected": ["<实体 id 或地物 id>"]}],
 "public_events": [],
 "state_patch": [{"op": "replace", "path": "/entities/<实体 id>/sheet/fields/<字段>", "value": 0}],
 "memory_entries": [{"entities": ["<实体 id>"], "features": [], "text": "..."}],
 "kp_notes": null,
 "game_over": false}
上面每个列表里的条目只是格式示例；没有的就给空列表。字段名必须和示例完全一致（例如移动的终点是 "to"，不是 "pos"）。
