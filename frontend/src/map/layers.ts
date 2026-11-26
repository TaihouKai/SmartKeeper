import type { DisplayMap, MapChangeView, MapFeatureProps } from "./types";

export interface RenderProps extends MapFeatureProps {
  destroyed: boolean;
  render_height: number;
}

/** 把已知的地图变化叠加到静态地物上：被毁的建筑只保留 above_z 以下的部分，整栋被毁的高度为底高。 */
export function applyChanges(
  map: DisplayMap,
  changes: MapChangeView[],
): GeoJSON.FeatureCollection<GeoJSON.Geometry, RenderProps> {
  const cut = new Map<string, number | null>();
  for (const c of changes) {
    if (c.status !== "destroyed") continue;
    const prev = cut.get(c.feature);
    if (c.above_z === null || prev === null) cut.set(c.feature, null);
    else cut.set(c.feature, prev === undefined ? c.above_z : Math.min(prev, c.above_z));
  }
  return {
    type: "FeatureCollection",
    features: map.features.map((f) => {
      const p = f.properties;
      let h = p.height;
      let destroyed = false;
      if (cut.has(p.id)) {
        destroyed = true;
        const c = cut.get(p.id);
        h = c === null || c === undefined ? p.min_height : Math.max(p.min_height, Math.min(h, c));
      }
      return { ...f, properties: { ...p, destroyed, render_height: h } };
    }),
  };
}

/** 高度的文字说明的消息代码与参数，例如“楼顶”“上空 100 米”。 */
export function heightCode(
  z: number,
  building?: { height: number } | null,
): { key: string; params: Record<string, number> } {
  if (building && Math.abs(z - building.height) < 0.5) return { key: "map.height.roof", params: {} };
  if (building && z >= 0 && z < building.height) {
    return { key: "map.height.floor", params: { floor: Math.floor(z / 3) + 1 } };
  }
  if (z < 0) return { key: "map.height.below", params: { m: Math.round(-z) } };
  if (z < 0.5) return { key: "map.height.ground", params: {} };
  return { key: "map.height.above", params: { m: Math.round(z) } };
}

/** 以一点为圆心、半径若干米的圆（经纬度多边形），用来在地图上画一片范围。 */
export function circle(lon: number, lat: number, meters: number, steps = 48): [number, number][] {
  const dLat = meters / 110540;
  const dLon = meters / (111320 * Math.cos((lat * Math.PI) / 180));
  const out: [number, number][] = [];
  for (let i = 0; i <= steps; i++) {
    const a = (2 * Math.PI * i) / steps;
    out.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]);
  }
  return out;
}

/** 地物的代表点（经纬度）：点就是它自己，面取外圈的平均，线取中间的一个点。 */
export function featureCenter(g: GeoJSON.Geometry): [number, number] | null {
  const avg = (ring: GeoJSON.Position[]): [number, number] | null => {
    if (!ring.length) return null;
    let x = 0;
    let y = 0;
    for (const p of ring) {
      x += p[0] ?? 0;
      y += p[1] ?? 0;
    }
    return [x / ring.length, y / ring.length];
  };
  const mid = (line: GeoJSON.Position[]): [number, number] | null => {
    const p = line[Math.floor(line.length / 2)];
    return p ? [p[0] ?? 0, p[1] ?? 0] : null;
  };
  switch (g.type) {
    case "Point":
      return [g.coordinates[0] ?? 0, g.coordinates[1] ?? 0];
    case "Polygon":
      return avg(g.coordinates[0] ?? []);
    case "MultiPolygon":
      return avg(g.coordinates[0]?.[0] ?? []);
    case "LineString":
      return mid(g.coordinates);
    case "MultiLineString":
      return mid(g.coordinates[0] ?? []);
    default:
      return null;
  }
}
