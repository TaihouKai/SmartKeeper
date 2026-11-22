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
