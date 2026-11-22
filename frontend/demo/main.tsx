/**
 * 地图组件的静态演示页：不依赖后端，只用假数据。
 * 地物来自 maps/demo_shibuya.geojson（scripts/make_demo_map.py 转成经纬度）。
 */
import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { I18nProvider, useI18n } from "../src/i18n";
import { MapView, heightCode, type DisplayMap, type MapChangeView, type MarkerView, type Pick } from "../src/map";
import demoMap from "./demo-map.json";

const MAP = demoMap as unknown as DisplayMap;

export const DEMO_MARKERS: MarkerView[] = [
  { ref: "h_me", label: "Aki", lon: 139.70125, lat: 35.65905, z: 0, own: true },
  { ref: "h_me2", label: "Bolt", lon: 139.70095, lat: 35.65935, z: 0, own: true },
  { ref: "h_1", label: "#1", lon: 139.7016, lat: 35.6594, z: 0, own: false },
  { ref: "h_2", label: "Grey coat", lon: 139.7003, lat: 35.6583, z: 0, own: false },
];

export const DEMO_CHANGES: MapChangeView[] = [
  { feature: "bldg_617560918", status: "destroyed", above_z: 120 },
];

function Demo() {
  const { t, lang, setLang } = useI18n();
  const [pick, setPick] = useState<Pick | null>(null);
  const selected = pick?.kind === "feature" ? pick.id : null;
  let info = t("demo.hint");
  if (pick?.kind === "entity") info = t("demo.picked_entity", { label: pick.label });
  if (pick?.kind === "feature") {
    const h = heightCode(pick.height, { height: pick.height });
    info = t("demo.picked_feature", { name: pick.name || pick.id, top: t(h.key, h.params) });
  }
  if (pick?.kind === "point") info = t("demo.picked_point", { lon: pick.lon.toFixed(5), lat: pick.lat.toFixed(5) });
  return (
    <main style={{ padding: 16, fontFamily: "system-ui, sans-serif", maxWidth: 960, margin: "0 auto" }}>
      <h1 style={{ fontSize: 20 }}>{t("demo.title")}</h1>
      <button onClick={() => setLang(lang === "zh" ? "en" : "zh")}>{t(lang === "zh" ? "lang.en" : "lang.zh")}</button>
      <MapView map={MAP} markers={DEMO_MARKERS} changes={DEMO_CHANGES} onPick={setPick} selected={selected} height="70vh" />
      <p data-testid="pick-info">{info}</p>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <I18nProvider>
      <Demo />
    </I18nProvider>
  </StrictMode>,
);
