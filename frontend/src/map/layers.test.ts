import { applyChanges, heightCode } from "./layers";
import type { DisplayMap } from "./types";

const square: GeoJSON.Polygon = { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] };
const map: DisplayMap = {
  type: "FeatureCollection",
  id: "m",
  name: "m",
  origin: { lon: 0, lat: 0 },
  bounds_lonlat: [0, 0, 1, 1],
  attribution: "osm",
  features: [
    { type: "Feature", geometry: square, properties: { id: "a", kind: "building", name: "", height: 30, min_height: 0 } },
    { type: "Feature", geometry: square, properties: { id: "b", kind: "building", name: "", height: 30, min_height: 5 } },
    { type: "Feature", geometry: square, properties: { id: "c", kind: "building", name: "", height: 30, min_height: 0 } },
  ],
};

describe("applyChanges", () => {
  it("cuts destroyed buildings", () => {
    const out = applyChanges(map, [
      { feature: "a", status: "destroyed", above_z: 12 },
      { feature: "b", status: "destroyed", above_z: null },
    ]);
    const by = Object.fromEntries(out.features.map((f) => [f.properties.id, f.properties]));
    expect(by.a?.render_height).toBe(12);
    expect(by.a?.destroyed).toBe(true);
    expect(by.b?.render_height).toBe(5);
    expect(by.c?.destroyed).toBe(false);
    expect(by.c?.render_height).toBe(30);
  });
});

describe("heightCode", () => {
  it("describes heights", () => {
    expect(heightCode(30, { height: 30 }).key).toBe("map.height.roof");
    expect(heightCode(7, { height: 30 })).toEqual({ key: "map.height.floor", params: { floor: 3 } });
    expect(heightCode(100)).toEqual({ key: "map.height.above", params: { m: 100 } });
    expect(heightCode(0).key).toBe("map.height.ground");
    expect(heightCode(-6)).toEqual({ key: "map.height.below", params: { m: 6 } });
  });
});
