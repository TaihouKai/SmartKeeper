# `mapdata`

真实地图导入、高度补全、坐标投影（离线工具）；地图文件的读取与校验。

- 依赖：`contracts`
- 地图文件：GeoJSON 地物集合，坐标已投影成以原点为基准的米（x 向东，y 向北）；格式见 `fileformat.py`。运行时只读文件，不联网。
- 导入：`uv run python -m smartkeeper.mapdata --bbox 南,西,北,东 --id <id> --name <名字>`（从 Overpass 下载，依次试几个公共镜像），或 `--overpass-file` 用已下载的数据。`--defaults` 指定建筑默认高度的 JSON。
- 高度补全（`heights.py`）：有 `height` 用它；否则 `building:levels × 3 米`；都没有按 `building=*` 取默认值。
- 投影（`projection.py`）：等距方位投影，往返误差远小于 1 米。
- 接口：`FileMapStore(dir)` 实现 `contracts.MapStore`；`display_geojson` 把地图转成给前端的经纬度 GeoJSON。
- 单独测试：`uv run pytest tests/mapdata`
