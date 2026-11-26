import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useI18n } from "../i18n";
import { applyChanges, circle } from "./layers";
import type { DisplayMap, FeatureKind, MapChangeView, MarkerView, Pick, PlaceView } from "./types";
import "./map.css";

export interface MapViewProps {
  map: DisplayMap;
  markers: MarkerView[];
  changes: MapChangeView[];
  onPick?: (pick: Pick) => void;
  selected?: string | null;
  height?: string;
  /** 点选的位置：插一个图钉 */
  pin?: { lon: number; lat: number } | null;
  /** 起了名字的地点：一直显示名字，点了算点选这个地点 */
  places?: PlaceView[];
  /** 把地图移到这里（key 变了才移，同一个地方可以再移一次） */
  focus?: { lon: number; lat: number; key: number } | null;
}

const COLORS = {
  background: "#ebe7df",
  park: "#bcd9a3",
  water: "#9cc3e6",
  road: "#ffffff",
  building: "#c9c2b6",
  buildingDestroyed: "#b3473a",
  landmark: "#7a5c2e",
};

/** 不加载任何底图瓦片：地图组件只用本局的静态地物，完全离线。 */
const BLANK_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": COLORS.background } }],
};

export function MapView({ map, markers, changes, onPick, selected, height = "60vh", pin = null, places = [], focus = null }: MapViewProps) {
  const { t } = useI18n();
  const container = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRefs = useRef<maplibregl.Marker[]>([]);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;
  // 地物 id -> 起了名字的地点的名字（鼠标提示用；地图只建一次，所以经 ref 读最新的）
  const placeNames = useRef(new Map<string, string>());
  placeNames.current = new Map(places.filter((p) => p.feature).map((p) => [p.feature!, p.name]));

  const data = useMemo(() => applyChanges(map, changes), [map, changes]);

  // 浏览器开不了 WebGL（显卡驱动、远程桌面、一些手机浏览器）：地图的位置显示一句提示，页面其余部分照常能用
  const [failed, setFailed] = useState(false);

  // 创建地图（只在地图本身变化时重建）
  useEffect(() => {
    if (!container.current) return;
    const [w, s, e, n] = map.bounds_lonlat;
    let m: maplibregl.Map;
    try {
      m = new maplibregl.Map({
        container: container.current,
        style: BLANK_STYLE,
        bounds: [
          [w, s],
          [e, n],
        ],
        pitch: 50,
        bearing: -15,
        attributionControl: false,
        maxPitch: 75,
      });
    } catch {
      setFailed(true);
      return;
    }
    m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    m.on("load", () => {
      m.addSource("features", { type: "geojson", data, promoteId: "id" });
      m.addLayer({
        id: "park",
        type: "fill",
        source: "features",
        filter: ["==", ["get", "kind"], "park"],
        paint: { "fill-color": COLORS.park },
      });
      m.addLayer({
        id: "water",
        type: "fill",
        source: "features",
        filter: ["==", ["get", "kind"], "water"],
        paint: { "fill-color": COLORS.water },
      });
      m.addLayer({
        id: "road",
        type: "line",
        source: "features",
        filter: ["==", ["get", "kind"], "road"],
        paint: { "line-color": COLORS.road, "line-width": 4 },
      });
      // 起了名字的一片范围（例如中立区）：半透明的圈
      m.addSource("areas", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({ id: "area-fill", type: "fill", source: "areas", paint: { "fill-color": "#7a5c2e", "fill-opacity": 0.12 } });
      m.addLayer({ id: "area-line", type: "line", source: "areas", paint: { "line-color": "#7a5c2e", "line-width": 2, "line-dasharray": [2, 2] } });
      m.addLayer({
        id: "landmark",
        type: "circle",
        source: "features",
        filter: ["==", ["get", "kind"], "landmark"],
        paint: { "circle-radius": 5, "circle-color": COLORS.landmark, "circle-stroke-color": "#fff", "circle-stroke-width": 1 },
      });
      m.addLayer({
        id: "building",
        type: "fill-extrusion",
        source: "features",
        filter: ["==", ["get", "kind"], "building"],
        paint: {
          "fill-extrusion-color": [
            "case",
            ["boolean", ["feature-state", "selected"], false],
            "#e0a800",
            ["get", "destroyed"],
            COLORS.buildingDestroyed,
            COLORS.building,
          ],
          "fill-extrusion-height": ["get", "render_height"],
          "fill-extrusion-base": ["get", "min_height"],
          "fill-extrusion-opacity": 0.92,
        },
      });
    });
    m.on("click", (ev) => {
      const hits = m.queryRenderedFeatures(ev.point, { layers: ["landmark", "building", "park", "water", "road"] });
      const top = hits[0];
      const cb = pickRef.current;
      if (!cb) return;
      if (top && top.properties) {
        const p = top.properties as Record<string, unknown>;
        cb({
          kind: "feature",
          id: String(p.id),
          name: typeof p.name === "string" ? p.name : "",
          featureKind: String(p.kind) as FeatureKind,
          height: Number(p.height),
          lon: ev.lngLat.lng,
          lat: ev.lngLat.lat,
        });
      } else {
        cb({ kind: "point", lon: ev.lngLat.lng, lat: ev.lngLat.lat });
      }
    });
    // 鼠标移到有名字的地点、建筑上：显示名字
    const tip = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8, className: "sk-map-tip" });
    for (const layer of ["landmark", "building"]) {
      m.on("mousemove", layer, (ev) => {
        const props = ev.features?.[0]?.properties;
        const name = placeNames.current.get(String(props?.id)) ?? props?.name;
        m.getCanvas().style.cursor = "pointer";
        if (typeof name === "string" && name) tip.setLngLat(ev.lngLat).setText(name).addTo(m);
        else tip.remove();
      });
      m.on("mouseleave", layer, () => {
        m.getCanvas().style.cursor = "";
        tip.remove();
      });
    }
    mapRef.current = m;
    return () => {
      markerRefs.current.forEach((mk) => mk.remove());
      markerRefs.current = [];
      m.remove();
      mapRef.current = null;
    };
    // data 在下一个 effect 里更新，这里故意只依赖地图本身
  }, [map]);

  // 地图变化更新
  useEffect(() => {
    const m = mapRef.current;
    if (!m) return;
    const apply = () => {
      const src = m.getSource("features") as maplibregl.GeoJSONSource | undefined;
      src?.setData(data);
    };
    if (m.isStyleLoaded()) apply();
    else m.once("load", apply);
  }, [data]);

  // 选中的地物高亮
  useEffect(() => {
    const m = mapRef.current;
    if (!m || !selected) return;
    const set = (v: boolean) => {
      if (m.getSource("features")) m.setFeatureState({ source: "features", id: selected }, { selected: v });
    };
    if (m.isStyleLoaded()) set(true);
    else m.once("load", () => set(true));
    return () => {
      if (m.getSource("features")) set(false);
    };
  }, [selected]);

  // 实体标记：HTML 标记，不需要字体文件
  useEffect(() => {
    const m = mapRef.current;
    if (!m) return;
    markerRefs.current.forEach((mk) => mk.remove());
    markerRefs.current = markers.map((mv) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = mv.own ? "sk-marker sk-marker-own" : "sk-marker";
      el.textContent = mv.label;
      el.title = mv.label;
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        pickRef.current?.({ kind: "entity", ref: mv.ref, label: mv.label });
      });
      return new maplibregl.Marker({ element: el, anchor: "bottom" }).setLngLat([mv.lon, mv.lat]).addTo(m);
    });
  }, [markers, map]);

  // 起了名字的地点：小旗子加名字
  const placeRefs = useRef<maplibregl.Marker[]>([]);
  useEffect(() => {
    const m = mapRef.current;
    placeRefs.current.forEach((mk) => mk.remove());
    placeRefs.current = [];
    if (!m) return;
    placeRefs.current = places.map((p) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = "sk-place";
      el.textContent = p.name;
      el.title = p.name;
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        pickRef.current?.({ kind: "place", id: p.id });
      });
      // 名字挂在位置的下方：点它时插的图钉在上方，不会挡住名字
      return new maplibregl.Marker({ element: el, anchor: "top", offset: [0, 4] }).setLngLat([p.lon, p.lat]).addTo(m);
    });
  }, [places, map]);

  // 起了名字的一片范围：画圈
  useEffect(() => {
    const m = mapRef.current;
    if (!m) return;
    const data: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: places
        .filter((p) => p.radius)
        .map((p) => ({ type: "Feature", properties: { name: p.name }, geometry: { type: "Polygon", coordinates: [circle(p.lon, p.lat, p.radius ?? 0)] } })),
    };
    const apply = () => (m.getSource("areas") as maplibregl.GeoJSONSource | undefined)?.setData(data);
    if (m.isStyleLoaded()) apply();
    else m.once("load", apply);
  }, [places, map]);

  // 移到指定的地方（例如点了消息里的地名）
  useEffect(() => {
    const m = mapRef.current;
    if (!m || !focus) return;
    m.flyTo({ center: [focus.lon, focus.lat], zoom: Math.max(m.getZoom(), 17), essential: true });
    // 只在 key 变了的时候移
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.key]);

  // 点选位置的图钉
  const pinRef = useRef<maplibregl.Marker | null>(null);
  useEffect(() => {
    const m = mapRef.current;
    pinRef.current?.remove();
    pinRef.current = null;
    if (!m || !pin) return;
    const el = document.createElement("div");
    el.className = "sk-pin";
    pinRef.current = new maplibregl.Marker({ element: el, anchor: "bottom" }).setLngLat([pin.lon, pin.lat]).addTo(m);
  }, [pin, map]);

  return (
    <div className="sk-map" style={{ height }}>
      {failed && <p className="sk-map-failed">{t("map.no_webgl")}</p>}
      <div ref={container} className="sk-map-canvas" aria-label={t("map.aria")} />
      <div className="sk-map-attribution">{map.attribution}</div>
    </div>
  );
}
