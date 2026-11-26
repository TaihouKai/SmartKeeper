import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useI18n } from "../i18n";
import { applyChanges } from "./layers";
import type { DisplayMap, FeatureKind, MapChangeView, MarkerView, Pick } from "./types";
import "./map.css";

export interface MapViewProps {
  map: DisplayMap;
  markers: MarkerView[];
  changes: MapChangeView[];
  onPick?: (pick: Pick) => void;
  selected?: string | null;
  height?: string;
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

export function MapView({ map, markers, changes, onPick, selected, height = "60vh" }: MapViewProps) {
  const { t } = useI18n();
  const container = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markerRefs = useRef<maplibregl.Marker[]>([]);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;

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
        });
      } else {
        cb({ kind: "point", lon: ev.lngLat.lng, lat: ev.lngLat.lat });
      }
    });
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

  return (
    <div className="sk-map" style={{ height }}>
      {failed && <p className="sk-map-failed">{t("map.no_webgl")}</p>}
      <div ref={container} className="sk-map-canvas" aria-label={t("map.aria")} />
      <div className="sk-map-attribution">{map.attribution}</div>
    </div>
  );
}
