# `spatial`

空间查询，纯函数：输入地图、地图变化和实体位置，输出命中清单。LLM 不做空间推理。

- 依赖：`contracts`（几何计算用 Shapely）
- 接口：`ShapelySpatial` 实现 `contracts.Spatial`：`within`、`sweep`（胶囊、长方体、球、锥）、`line_of_sight`、`perceivable`、`distance`、`locate`、`in_bounds`、`inside_feature`、`feature_within`
- 建筑一律当作柱体：先在平面上求交，再比较那一段的高度与建筑的底高、顶高。被毁的建筑（`map_changes`）不再遮挡视线、不再被命中；`above_z` 表示只毁掉该高度以上。
- 视线：楼底闭、楼顶开——地面上的视线会被楼挡住，正好贴着楼顶的视线不算被挡。
- 感知：距离 ≤ 观察者感知半径 × 对方匿踪系数，并且有视线或在同一栋建筑内。可以是单向的。
- 简化：锥形命中建筑时用整个锥体的高度范围与建筑求交。
- 单独测试：`uv run pytest tests/spatial`（手写小地图，不导入 eventlog、world、kp、web）
