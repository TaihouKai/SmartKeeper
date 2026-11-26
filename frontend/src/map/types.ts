/** 地图组件的输入类型。全部是经纬度：米制坐标到经纬度的换算在后端完成。 */

export type FeatureKind = "building" | "road" | "park" | "water" | "landmark";

export interface MapFeatureProps {
  id: string;
  kind: FeatureKind;
  name: string;
  height: number;
  min_height: number;
}

export interface DisplayMap {
  type: "FeatureCollection";
  id: string;
  name: string;
  origin: { lon: number; lat: number };
  bounds_lonlat: [number, number, number, number];
  attribution: string;
  features: GeoJSON.Feature<GeoJSON.Geometry, MapFeatureProps>[];
}

export interface MapChangeView {
  feature: string;
  status: "destroyed";
  above_z: number | null;
}

/** 地图上的一个实体标记。own=true 是自己控制的实体（显示角色名），否则显示代号。 */
export interface MarkerView {
  ref: string;
  label: string;
  lon: number;
  lat: number;
  z: number;
  own: boolean;
}

/** 起了名字的地点：地图上一直显示名字。 */
export interface PlaceView {
  id: string;
  name: string;
  lon: number;
  lat: number;
  feature?: string | null; // 所在的地物（例如这栋楼）：鼠标移到这栋楼上显示这个名字
}

export type Pick =
  | { kind: "entity"; ref: string; label: string }
  | { kind: "place"; id: string }
  | { kind: "feature"; id: string; name: string; featureKind: FeatureKind; height: number; lon: number; lat: number }
  | { kind: "point"; lon: number; lat: number };
