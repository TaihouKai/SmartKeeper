import { useEffect, useMemo, useState } from "react";
import { api, call, withGame, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { IntelFacts } from "./intel";
import { MapView, featureCenter, heightCode, type DisplayMap, type MarkerView, type Pick, type PlaceView } from "../map";
import type { PlaceTarget } from "./PlaceText";
import { ErrorBox, LangSwitch, formatDuration, formatGameTime } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";
import { ReactionPanel } from "./ReactionPanel";
import { showNumber, withUnit } from "../ui/choices";
import { ChatPanel, type ChannelKey, type Mentionable } from "./ChatPanel";
import { ActionPlanProvider, usePlanState, useActionPlan, type Skill } from "./actionPlan";

/** 地图上点选的地方：位置（经纬度和米制坐标）、点到的地物（没有是空地）、我的角色走过去要多久。 */
type Picked = {
  lon: number;
  lat: number;
  x: number;
  y: number;
  feature: { id: string; name: string; kind: string; height: number } | null;
  list: Schemas["TravelOut"][];
  title?: string; // 起了名字的地点：卡片上写这个名字
  z?: number; // 这个地点的高度（例如楼里的某一层）
};

const FLOOR_M = 3; // 一层按 3 米算（和地图的高度说明一致）

/** 点选卡片：这是哪里、走过去要多久；可以设为目的地（建筑可以选地面、楼顶或第几层），有名字的可以在行动里提到它。 */
function PickCard({ picked, onDestination, onMention, onClose }: { picked: Picked; onDestination: (label: string, z: number) => void; onMention: () => void; onClose: () => void }) {
  const { t } = useI18n();
  const f = picked.feature;
  const height = f && f.kind === "building" ? Math.max(0, f.height) : 0;
  const floors = Math.max(1, Math.floor(height / FLOOR_M));
  const z0 = picked.z ?? 0;
  const [where, setWhere] = useState<"ground" | "floor" | "roof">(height > 0 && z0 > 0 ? (Math.abs(z0 - height) < 0.5 ? "roof" : "floor") : "ground");
  const [floor, setFloor] = useState(Math.floor(z0 / FLOOR_M) + 1);
  const z = where === "roof" ? height : where === "floor" ? Math.min(height, (Math.min(Math.max(floor, 1), floors) - 1) * FLOOR_M) : 0;
  const place = picked.title || f?.name || (f ? t(`map.kind.${f.kind}`) : t("kp.a_point"));
  const h = heightCode(z, height ? { height } : null);
  const heightText = t(h.key, Object.fromEntries(Object.entries(h.params).map(([k, v]) => [k, String(v)])));
  const label = where === "ground" ? place : `${place} · ${heightText}`;
  return (
    <div className="pl-travel sk-card">
      <div className="pl-pick-head">
        <strong>{place}</strong>
        {f && place !== t(`map.kind.${f.kind}`) && <span className="sk-hint">{picked.title && f.name && f.name !== picked.title ? `${f.name} · ` : ""}{t(`map.kind.${f.kind}`)}</span>}
        {height > 0 && <span className="sk-hint">{t("map.building_size", { m: String(Math.round(height)), n: String(floors) })}</span>}
      </div>
      {height > 0 && (
        <div className="pl-pick-height">
          <label className="sk-inline">
            <input type="radio" checked={where === "ground"} onChange={() => setWhere("ground")} /> {t("map.height.ground")}
          </label>
          <label className="sk-inline">
            <input type="radio" checked={where === "floor"} onChange={() => setWhere("floor")} />{" "}
            <input type="number" min={1} max={floors} value={floor} onFocus={() => setWhere("floor")} onChange={(e) => setFloor(Number(e.target.value) || 1)} /> {t("map.floor_unit")}
          </label>
          <label className="sk-inline">
            <input type="radio" checked={where === "roof"} onChange={() => setWhere("roof")} /> {t("map.height.roof")}
          </label>
        </div>
      )}
      <ul>
        {picked.list.map((x) => (
          <li key={x.ref}>
            {x.name}: {x.seconds === null || x.seconds === undefined ? t("play.travel_none") : t(x.fly ? "play.travel_fly" : "play.travel_walk", { time: formatDuration(t, x.seconds) })}
          </li>
        ))}
      </ul>
      <div className="sk-row">
        <button className="sk-primary" onClick={() => onDestination(label, z)}>
          {t("play.use_destination")}
        </button>
        {(picked.title || f?.name) && <button onClick={onMention}>{t("map.mention_it")}</button>}
        <button className="sk-link" onClick={onClose}>
          {t("play.close")}
        </button>
      </div>
    </div>
  );
}

/** 顶栏：游戏内时间、轮到谁、角色卡、规则书、剧本、语言。只显示自己的时间和状态，没有回合数和全局进度。 */
function TopBar({ status, onSheet }: { status: Schemas["StatusOut"] | null; onSheet: () => void }) {
  const { t, lang } = useI18n();
  const phase = !status ? "" : status.game_status === "ended" ? t("status.ended") : status.game_status === "running" ? t(`status.me.${status.me}`) : t("status.not_started");
  return (
    <header className="pl-top sk-statusbar">
      {status && <span className="pl-time">{formatGameTime(status.start_time, status.game_seconds, lang)}</span>}
      <span className={`pl-phase ${status?.me === "act" ? "go" : ""}`}>{phase}</span>
      <span className="pl-spacer" />
      <button type="button" className="sk-link" onClick={onSheet}>
        {t("play.tab.sheet")}
      </button>
      <a href={withGame("/rulebook")} target="_blank" rel="noreferrer">
        {t("handbook.title")}
      </a>
      <a href={withGame("/scenario")} target="_blank" rel="noreferrer">
        {t("handbook.scenario")}
      </a>
      <a href="/">{t("join.to_lobby")}</a>
      <LangSwitch onChange={(l) => void api.POST("/api/lang", { body: { lang: l } })} />
    </header>
  );
}

/** 地图下面的“身边”：我每个角色此刻感知到的人、见过的人、结盟。点名字就是在行动里 @ 他。 */
function ScenePanel({
  scene,
  onPick,
  onRename,
  canTalk,
  onTalk,
}: {
  scene: Schemas["SceneOut"];
  onPick: (p: Pick) => void;
  onRename: (ref: string, label: string, note: string) => Promise<void>;
  canTalk: boolean;
  onTalk: (from: string, to: string) => void;
}) {
  const { t } = useI18n();
  const allies = usePoll(() => call(api.GET("/api/alliances")), 10_000);
  const ally = useAction();
  const allyDo = (fn: () => Promise<unknown>) =>
    void ally.run(async () => {
      await fn();
      void allies.refresh();
    });
  const propose = (ref: string) => allyDo(() => call(api.POST("/api/alliances", { body: { ref } })));
  const [editing, setEditing] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const rename = (ref: string, l: string, n: string) => {
    setEditing(ref);
    setLabel(l);
    setNote(n);
  };
  const pending = (allies.data?.incoming.length ?? 0) > 0;
  // 有提议或盟友时展开（有人等我回应时更要看见）
  const anyAlliance = pending || (allies.data?.outgoing.length ?? 0) + (allies.data?.allies.length ?? 0) > 0;
  return (
    <div className="pl-scene">
      {scene.entities.map((e) => (
        <section key={e.ref} className="pl-scene-block">
          <h4>
            {e.name} <span className="sk-hint">{t("play.presence")}</span>
          </h4>
          {e.presence.length === 0 && <p className="sk-hint">{t("play.nobody")}</p>}
          {(e.placements ?? []).length > 0 && (
            <p className="sk-hint">
              {t("play.placements")} {(e.placements ?? []).map((x) => (x.mine ? x.label : t("play.placement_unknown"))).join("、")}
            </p>
          )}
          <ul className="pl-people">
            {e.presence.map((p) => (
              <li key={p.ref}>
                <button type="button" className="pl-person" onClick={() => onPick({ kind: "entity", ref: p.ref, label: p.label })} title={t("play.mention_hint")}>
                  @{p.label}
                </button>
                {p.note && <span className="sk-hint"> {p.note}</span>}
                <span className="pl-person-actions">
                  {canTalk && (
                    <button type="button" className="sk-link" onClick={() => onTalk(e.ref, p.ref)}>
                      {t("play.talk")}
                    </button>
                  )}
                  <button type="button" className="sk-link" onClick={() => propose(p.ref)}>
                    {t("alliance.propose")}
                  </button>
                  <button type="button" className="sk-link" onClick={() => rename(p.ref, p.label, p.note)}>
                    {t("play.rename")}
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {scene.seen.length > 0 && (
        <section className="pl-scene-block">
          <h4>{t("play.seen")}</h4>
          <ul className="pl-people">
            {scene.seen.map((s) => (
              <li key={s.ref}>
                <button type="button" className="pl-person" onClick={() => onPick({ kind: "entity", ref: s.ref, label: s.label })} title={t("play.mention_hint")}>
                  @{s.label}
                </button>
                {s.note && <span className="sk-hint"> {s.note}</span>}
                <span className="pl-person-actions">
                  <button type="button" className="sk-link" onClick={() => rename(s.ref, s.label, s.note)}>
                    {t("play.rename")}
                  </button>
                  <button type="button" className="sk-link" onClick={() => propose(s.ref)}>
                    {t("alliance.propose")}
                  </button>
                </span>
                {(s.intel ?? []).length > 0 && (
                  <details className="sk-intel-box">
                    <summary>{t("play.intel", { n: String((s.intel ?? []).length) })}</summary>
                    <IntelFacts facts={s.intel ?? []} />
                  </details>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {editing && (
        <section className="pl-scene-block pl-rename">
          <label>
            {t("play.handle_label")}
            <input value={label} onChange={(e) => setLabel(e.target.value)} />
          </label>
          <label>
            {t("play.handle_note")}
            <input value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <div className="sk-row">
            <button className="sk-primary" onClick={() => void onRename(editing, label, note).then(() => setEditing(null))}>
              {t("common.save")}
            </button>
            <button className="sk-link" onClick={() => setEditing(null)}>
              {t("common.cancel")}
            </button>
          </div>
        </section>
      )}
      <details className="pl-scene-block pl-alliance" open={anyAlliance}>
        <summary>
          <strong>{t("alliance.title")}</strong>
          {pending && <span className="pl-badge">{allies.data?.incoming.length}</span>}
        </summary>
        <p className="sk-hint">{t("alliance.hint")}</p>
        <ErrorBox error={ally.error} />
        {allies.data && allies.data.incoming.length + allies.data.outgoing.length + allies.data.allies.length === 0 && <p className="sk-hint">{t("alliance.none")}</p>}
        <ul>
          {(allies.data?.incoming ?? []).map((x) => (
            <li key={x.id}>
              {t("alliance.incoming", { who: x.who })}{" "}
              <button className="sk-link" onClick={() => allyDo(() => call(api.POST("/api/alliances/{item}/answer", { params: { path: { item: x.id } }, body: { accept: true } })))}>
                {t("alliance.accept")}
              </button>
              <button className="sk-link" onClick={() => allyDo(() => call(api.POST("/api/alliances/{item}/answer", { params: { path: { item: x.id } }, body: { accept: false } })))}>
                {t("alliance.decline")}
              </button>
            </li>
          ))}
          {(allies.data?.outgoing ?? []).map((x) => (
            <li key={x.id}>
              {t("alliance.outgoing", { who: x.who })}{" "}
              <button className="sk-link" onClick={() => allyDo(() => call(api.DELETE("/api/alliances/{item}", { params: { path: { item: x.id } } })))}>
                {t("alliance.cancel")}
              </button>
            </li>
          ))}
          {(allies.data?.allies ?? []).map((x) => (
            <li key={x.id}>
              {t("alliance.ally", { who: x.who })}{" "}
              <button className="sk-link" onClick={() => allyDo(() => call(api.DELETE("/api/alliances/{item}", { params: { path: { item: x.id } } })))}>
                {t("alliance.break")}
              </button>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

/** 角色卡：从顶栏打开的侧栏。数值、条目、状态、改动记录。 */
function SheetDrawer({ onClose, onUse }: { onClose: () => void; onUse: (s: Skill) => void }) {
  const { t } = useI18n();
  const { skills } = useActionPlan();
  const sheets = usePoll(() => call(api.GET("/api/sheets")), 30_000);
  const rules = usePoll(() => call(api.GET("/api/rules")), 600_000);
  const [hist, setHist] = useState<string | null>(null);
  return (
    <aside className="sk-drawer pl-sheet" aria-label={t("play.tab.sheet")}>
      <div className="sk-drawer-head">
        <h3>{t("play.tab.sheet")}</h3>
        <button type="button" className="sk-link" onClick={onClose}>
          {t("play.close")}
        </button>
      </div>
      {(sheets.data ?? []).map((s) => {
        const tpl = ((rules.data?.templates ?? []) as unknown as Schemas["EntityTemplate"][]).find((x) => x.name === s.template);
        const fdef = (k: string) => tpl?.fields?.find((f) => f.name === k);
        const ddef = (k: string) => tpl?.derived?.find((d) => d.name === k);
        const sheet = s.sheet as { name?: string; fields?: Record<string, unknown>; groups?: Record<string, { name: string; description?: string }[]>; statuses?: { tag: string }[] };
        return (
          <section key={s.entity_id} className="pl-sheet-card">
            <h3>{s.label || sheet.name}</h3>
            {skills.some((x) => x.entity_id === s.entity_id) && (
              <div className="pl-skills">
                <strong>{t("skill.title")}</strong>
                <ul>
                  {skills
                    .filter((x) => x.entity_id === s.entity_id)
                    .map((x) => (
                      <li key={x.name}>
                        <button type="button" className="sk-primary" disabled={x.cooldown} onClick={() => onUse(x)}>
                          {t("skill.use")}
                        </button>{" "}
                        <b>{x.name}</b> <span className="sk-hint">{x.group_label || x.group}{x.toggle_on !== null && x.toggle_on !== undefined ? ` · ${t(x.toggle_on ? "plan.on" : "plan.off")}` : ""}{x.cooldown ? ` · ${t("skill.cooldown")}` : ""}</span>
                        {x.description && <div className="sk-hint pl-skill-desc">{x.description}</div>}
                      </li>
                    ))}
                </ul>
              </div>
            )}
            <table className="sk-table">
              <tbody>
                {Object.entries(sheet.fields ?? {}).map(([k, v]) => (
                  <tr key={k}>
                    <th>{fdef(k)?.label || k}</th>
                    <td>{typeof v === "boolean" ? t(v ? "sheet.yes" : "sheet.no") : typeof v === "number" ? (fdef(k)?.choices?.length ? showNumber(fdef(k)?.choices, v) : withUnit(v, fdef(k)?.unit)) : String(v)}</td>
                  </tr>
                ))}
                {s.derived.map((d) => (
                  <tr key={d.name}>
                    <th>{ddef(d.name)?.label || d.name}</th>
                    <td>{withUnit(d.value, ddef(d.name)?.unit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {Object.entries(sheet.groups ?? {}).map(([g, entries]) => (
              <details key={g}>
                <summary>
                  <strong>{tpl?.groups?.find((x) => x.name === g)?.label || g}</strong> <span className="sk-hint">({entries.length})</span>
                </summary>
                <ul>
                  {entries.map((en, i) => (
                    <li key={i}>
                      <strong>{en.name}</strong> <span className="sk-hint">{en.description}</span>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
            {(sheet.statuses ?? []).length > 0 && (
              <p>
                <strong>{t("sheet.statuses")}</strong> {(sheet.statuses ?? []).map((x) => x.tag).join(", ")}
              </p>
            )}
            <button className="sk-link" onClick={() => setHist(hist === s.entity_id ? null : s.entity_id)}>
              {t("sheet.history")} ({s.history.length})
            </button>
            {hist === s.entity_id && (
              <ul className="sk-hint">
                {s.history.map((h, i) => (
                  <li key={i}>
                    {t("sheet.change", { path: h.path, old: JSON.stringify(h.old), new: JSON.stringify(h.new) })}
                    {h.source_seq ? ` #${h.source_seq}` : ""} · {t(`sheet.source.${h.source_kind}`)}
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </aside>
  );
}

/** 游戏页：一屏。左边地图和身边的人，右边聊天（KP、广播、对话、私聊都是会话）；角色卡在侧栏。每 10 秒左右轮询。 */
export function PlayPage() {
  const { t } = useI18n();
  const [channel, setChannel] = useState<ChannelKey>("kp");
  const [draft, setDraft] = useState("");
  const [quotes, setQuotes] = useState<number[]>([]);
  const [sheetOpen, setSheetOpen] = useState(false);
  const inTalk = channel.startsWith("talk:");
  const status = usePoll(() => call(api.GET("/api/status")), 10_000);
  const events = usePoll(() => call(api.GET("/api/events", { params: { query: { since: 0 } } })), 8_000);
  const scene = usePoll(() => call(api.GET("/api/scene")), 10_000);
  const skills = usePoll(() => call(api.GET("/api/skills")), 15_000);
  const map = usePoll(async () => (await call(api.GET("/api/map"))) as unknown as DisplayMap, 3_600_000);
  const talks = usePoll(() => call(api.GET("/api/talks")), inTalk ? 2_000 : 6_000, [inTalk]);
  const [picked, setPicked] = useState<Picked | null>(null);
  const [focus, setFocus] = useState<{ lon: number; lat: number; key: number } | null>(null);
  const err = useAction();
  const evs = events.data ?? [];
  // 来了新消息（例如 KP 的反馈、新一轮开始）：马上刷新状态和场景，不等各自的定时刷新
  const lastSeq = evs.length ? evs[evs.length - 1]!.seq : 0;
  useEffect(() => {
    if (!lastSeq) return;
    void status.refresh();
    void scene.refresh();
    void skills.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastSeq]);
  const refresh = () => {
    void status.refresh();
    void events.refresh();
    void scene.refresh();
    void talks.refresh();
    void skills.refresh();
  };
  const mentionables: Mentionable[] = useMemo(() => {
    const s = scene.data;
    if (!s) return [];
    const out = new Map<string, Mentionable>();
    s.entities.forEach((e) => out.set(e.ref, { ref: e.ref, label: e.name, kind: t("at.own") }));
    s.seen.forEach((p) => out.set(p.ref, { ref: p.ref, label: p.label, kind: t("at.seen") }));
    s.entities.forEach((e) => e.presence.forEach((p) => out.set(p.ref, { ref: p.ref, label: p.label, kind: t("at.near") })));
    // 我知道名字的地点：在楼里地面上的写成这栋楼，其余写成坐标（带高度）
    for (const p of s.places ?? []) {
      const ref = p.feature && p.pos.z < 0.5 ? `feature:${p.feature}` : `point:${Math.round(p.pos.x * 10) / 10},${Math.round(p.pos.y * 10) / 10},${Math.round(p.pos.z * 10) / 10}`;
      out.set(`place:${p.id}`, { ref, label: p.name, kind: t("at.place") });
    }
    return [...out.values()];
  }, [scene.data, t]);
  // 本回合行动：自己的角色、能用的技能和动作；行动列表（地图上设目的地、角色卡上点“使用”也往里加）
  const own = useMemo(() => (scene.data?.entities ?? []).map((e) => ({ ref: e.ref, name: e.name })), [scene.data]);
  const skillList = useMemo<Skill[]>(() => {
    const names = new Map(own.map((o) => [o.ref, o.name]));
    return (skills.data ?? []).map((s) => ({ ...s, owner: names.get(s.entity_id) ?? "?" }));
  }, [skills.data, own]);
  const planState = usePlanState(own, skillList);
  const placeViews = useMemo<PlaceView[]>(() => (scene.data?.places ?? []).map((p) => ({ id: p.id, name: p.name, lon: p.pos.lon, lat: p.pos.lat, feature: p.feature, radius: p.radius })), [scene.data]);
  const markers = useMemo<MarkerView[]>(() => {
    const s = scene.data;
    if (!s) return [];
    const out = new Map<string, MarkerView>();
    // 自己的几个角色站在同一个地方（例如主角和同伴在一起）：合成一个标记，免得叠在一起只看得到一个
    const together = new Map<string, MarkerView>();
    for (const e of s.entities) {
      if (!e.pos) continue;
      const spot = `${e.pos.lon.toFixed(5)},${e.pos.lat.toFixed(5)},${Math.round(e.pos.z)}`;
      const here = together.get(spot);
      if (here) here.label = [here.label, e.name].join("\n"); // 一人一行，不挤在一行里被截断
      else together.set(spot, { ref: e.ref, label: e.name, lon: e.pos.lon, lat: e.pos.lat, z: e.pos.z, own: true });
    }
    for (const m of together.values()) out.set(m.ref, m);
    for (const e of s.entities) {
      for (const p of e.presence) out.set(p.ref, { ref: p.ref, label: p.label, lon: p.pos.lon, lat: p.pos.lat, z: p.pos.z, own: false });
      for (const x of e.placements ?? []) out.set(x.ref, { ref: x.ref, label: x.label || t("play.placement_unknown"), lon: x.pos.lon, lat: x.pos.lat, z: x.pos.z, own: x.mine });
    }
    return [...out.values()];
  }, [scene.data, t]);

  if (status.error && !status.data) {
    return (
      <main className="sk-page">
        <p>{t("join.no_session")}</p>
        <p>
          <a className="sk-button sk-primary" href="/">
            {t("join.to_lobby")}
          </a>
        </p>
      </main>
    );
  }

  // 点人就是在行动里 @ 他；点地图上别的地方（建筑、地点、空地）先插图钉，看看是哪里、走过去要多久，再决定
  const onPick = (p: Pick) =>
    void err.run(async () => {
      if (p.kind === "entity") {
        setDraft(`${draft}@[${p.label}](${p.ref}) `);
        setChannel("kp");
        return;
      }
      if (p.kind === "place") {
        await openPlace({ kind: "place", id: p.id, name: "" });
        return;
      }
      const feature = p.kind === "feature" ? { id: p.id, name: p.name, kind: p.featureKind, height: p.height } : null;
      // 点到的地物是一个我知道名字的地点（例如教会所在的楼）：卡片上写这个名字
      // 一栋楼有几个名字时（例如“教会”和一片范围“教会中立区”）用不带范围的、最短的那个
      const named = feature
        ? (scene.data?.places ?? []).filter((x) => x.feature === feature.id).sort((a, b) => Number(Boolean(a.radius)) - Number(Boolean(b.radius)) || a.name.length - b.name.length)[0]
        : undefined;
      await openAt(p.lon, p.lat, feature, named?.name);
    });
  // 在一个位置插图钉、开卡片：是哪里、走过去要多久
  const openAt = async (lon: number, lat: number, feature: Picked["feature"], title?: string, z?: number, fly = false) => {
    const m = await call(api.GET("/api/map/project", { params: { query: { lon, lat } } }));
    const list = await call(api.GET("/api/travel", { params: { query: { lon, lat } } }));
    setPicked({ lon, lat, x: m.x, y: m.y, feature, list, title, z });
    if (fly) setFocus({ lon, lat, key: Date.now() });
  };
  const featureInfo = (id: string): Picked["feature"] => {
    const f = map.data?.features.find((x) => x.properties.id === id);
    return f ? { id, name: f.properties.name, kind: f.properties.kind, height: f.properties.height } : null;
  };
  // 消息里点了地名、地图上点了地名的小旗子：移过去，开卡片
  const openPlace = async (target: PlaceTarget) => {
    if (target.kind === "place") {
      const p = scene.data?.places?.find((x) => x.id === target.id);
      if (!p) return;
      await openAt(p.pos.lon, p.pos.lat, p.feature ? featureInfo(p.feature) : null, p.name, p.pos.z, true);
      return;
    }
    const f = map.data?.features.find((x) => x.properties.id === target.id);
    const c = f ? featureCenter(f.geometry) : null;
    if (!c) return;
    await openAt(c[0], c[1], featureInfo(target.id), target.name, undefined, true);
  };
  // 设为目的地：给选中的角色加一条移动（可以勾选和谁一起走）
  const useDestination = (label: string, z: number) => {
    if (!picked || !planState.actor) return;
    const f = picked.feature;
    const to = f ? { feature: f.id, z: f.kind === "building" ? z : null } : { point: { x: Math.round(picked.x * 10) / 10, y: Math.round(picked.y * 10) / 10, z } };
    planState.add({ actor: planState.actor, to: { to, label }, companions: [], params: {} });
    setPicked(null);
    setChannel("kp");
  };
  const mentionPicked = () => {
    if (!picked) return;
    const f = picked.feature;
    const label = picked.title || f?.name || f?.id || t("kp.a_point");
    const ref = f ? `feature:${f.id}` : `point:${Math.round(picked.x * 10) / 10},${Math.round(picked.y * 10) / 10},${picked.z ?? 0}`;
    setDraft(`${draft}@[${label}](${ref}) `);
    setPicked(null);
    setChannel("kp");
  };
  // 角色卡上点“使用”：在行动面板里选对象和参数（不用的直接加进行动列表）
  const pickSkill = (s: Skill) => {
    planState.setActor(s.entity_id);
    if (s.target === "single" || s.params.length > 0) planState.setConfiguring(s);
    else planState.add({ actor: s.entity_id, entry: s.name, companions: [], params: {} });
    setChannel("kp");
  };
  const startTalk = (from: string, to: string) =>
    void err.run(async () => {
      const talk = await call(api.POST("/api/talks", { body: { to, from } }));
      await talks.refresh();
      setChannel(`talk:${talk.id}`);
    });

  return (
    <ActionPlanProvider value={planState}>
    <div className="pl-shell">
      <TopBar status={status.data} onSheet={() => setSheetOpen(true)} />
      <ReactionPanel onDone={refresh} />
      <ErrorBox error={err.error} />
      <div className="pl-main">
        <section className="pl-left">
          <div className="pl-map">
            {map.data && scene.data ? <MapView map={map.data} markers={markers} changes={scene.data.map_changes} onPick={onPick} height="100%" pin={picked ? { lon: picked.lon, lat: picked.lat } : null} places={placeViews} focus={focus} /> : <p className="sk-hint">{t("common.loading")}</p>}
            {picked && <PickCard key={`${picked.lon},${picked.lat}`} picked={picked} onDestination={useDestination} onMention={mentionPicked} onClose={() => setPicked(null)} />}
            <p className="pl-map-hint">{t("play.map_hint")}</p>
          </div>
          {scene.data && (
            <ScenePanel
              scene={scene.data}
              onPick={onPick}
              onRename={async (ref, label, note) => {
                await err.run(() => call(api.PATCH("/api/handles/{ref}", { params: { path: { ref } }, body: { label, note } })));
                void scene.refresh();
              }}
              canTalk={status.data?.me === "act" || status.data?.me === "change" || status.data?.me === "submitted"}
              onTalk={startTalk}
            />
          )}
        </section>
        <ChatPanel
          events={evs}
          status={status.data}
          talks={talks.data ?? []}
          channel={channel}
          setChannel={setChannel}
          draft={draft}
          setDraft={setDraft}
          quotes={quotes}
          setQuotes={setQuotes}
          mentionables={mentionables}
          onChanged={refresh}
          places={scene.data?.places ?? []}
          onPlace={(p) => void err.run(() => openPlace(p))}
          onPerson={(p) => onPick({ kind: "entity", ref: p.ref, label: p.name })}
        />
      </div>
      {sheetOpen && (
        <SheetDrawer
          onClose={() => setSheetOpen(false)}
          onUse={(s) => {
            pickSkill(s);
            setSheetOpen(false);
          }}
        />
      )}
    </div>
    </ActionPlanProvider>
  );
}
