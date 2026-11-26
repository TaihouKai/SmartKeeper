import { useMemo, useState } from "react";
import { api, call, withGame, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { IntelFacts } from "./intel";
import { MapView, type DisplayMap, type MarkerView, type Pick } from "../map";
import { ErrorBox, LangSwitch, formatDuration, formatGameTime } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";
import { ReactionPanel } from "./ReactionPanel";
import { showNumber, withUnit } from "../ui/choices";
import { ChatPanel, type ChannelKey, type Mentionable } from "./ChatPanel";

type Travel = { x: number; y: number; list: Schemas["TravelOut"][] };

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
function SheetDrawer({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
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
            <h3>{sheet.name}</h3>
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
  const map = usePoll(async () => (await call(api.GET("/api/map"))) as unknown as DisplayMap, 3_600_000);
  const talks = usePoll(() => call(api.GET("/api/talks")), inTalk ? 2_000 : 6_000, [inTalk]);
  const [travel, setTravel] = useState<Travel | null>(null);
  const err = useAction();
  const evs = events.data ?? [];
  const refresh = () => {
    void status.refresh();
    void events.refresh();
    void scene.refresh();
    void talks.refresh();
  };
  const mentionables: Mentionable[] = useMemo(() => {
    const s = scene.data;
    if (!s) return [];
    const out = new Map<string, Mentionable>();
    s.entities.forEach((e) => out.set(e.ref, { ref: e.ref, label: e.name }));
    s.entities.forEach((e) => e.presence.forEach((p) => out.set(p.ref, { ref: p.ref, label: p.label })));
    s.seen.forEach((p) => out.set(p.ref, { ref: p.ref, label: p.label }));
    return [...out.values()];
  }, [scene.data]);
  const markers = useMemo<MarkerView[]>(() => {
    const s = scene.data;
    if (!s) return [];
    const out = new Map<string, MarkerView>();
    for (const e of s.entities) {
      if (e.pos) out.set(e.ref, { ref: e.ref, label: e.name, lon: e.pos.lon, lat: e.pos.lat, z: e.pos.z, own: true });
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

  // 地图和身边的人：点人或地物就是在行动里 @ 它；点地面先看走过去要多久
  const onPick = (p: Pick) =>
    void err.run(async () => {
      if (p.kind === "entity") setDraft(`${draft}@[${p.label}](${p.ref}) `);
      else if (p.kind === "feature") setDraft(`${draft}@[${p.name || p.id}](feature:${p.id}) `);
      else {
        const m = await call(api.GET("/api/map/project", { params: { query: { lon: p.lon, lat: p.lat } } }));
        const list = await call(api.GET("/api/travel", { params: { query: { lon: p.lon, lat: p.lat } } }));
        setTravel({ x: m.x, y: m.y, list });
        return;
      }
      setChannel("kp");
    });
  const useDestination = () => {
    if (!travel) return;
    setDraft(`${draft}@[${t("kp.a_point")}](point:${travel.x},${travel.y},0) `);
    setTravel(null);
    setChannel("kp");
  };
  const startTalk = (from: string, to: string) =>
    void err.run(async () => {
      const talk = await call(api.POST("/api/talks", { body: { to, from } }));
      await talks.refresh();
      setChannel(`talk:${talk.id}`);
    });

  return (
    <div className="pl-shell">
      <TopBar status={status.data} onSheet={() => setSheetOpen(true)} />
      <ReactionPanel onDone={refresh} />
      <ErrorBox error={err.error} />
      <div className="pl-main">
        <section className="pl-left">
          <div className="pl-map">
            {map.data && scene.data ? <MapView map={map.data} markers={markers} changes={scene.data.map_changes} onPick={onPick} height="100%" /> : <p className="sk-hint">{t("common.loading")}</p>}
            {travel && (
              <div className="pl-travel sk-card">
                <strong>{t("play.travel_title")}</strong>
                <ul>
                  {travel.list.map((x) => (
                    <li key={x.ref}>
                      {x.name}: {x.seconds === null || x.seconds === undefined ? t("play.travel_none") : t(x.fly ? "play.travel_fly" : "play.travel_walk", { time: formatDuration(t, x.seconds) })}
                    </li>
                  ))}
                </ul>
                <div className="sk-row">
                  <button className="sk-primary" onClick={useDestination}>
                    {t("play.use_destination")}
                  </button>
                  <button className="sk-link" onClick={() => setTravel(null)}>
                    {t("play.close")}
                  </button>
                </div>
              </div>
            )}
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
              canTalk={status.data?.me === "act" || status.data?.me === "submitted"}
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
        />
      </div>
      {sheetOpen && <SheetDrawer onClose={() => setSheetOpen(false)} />}
    </div>
  );
}
