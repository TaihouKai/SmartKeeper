import { useMemo, useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { MapView, type DisplayMap, type MarkerView, type Pick } from "../map";
import { ErrorBox, LangSwitch, Tabs, formatGameTime } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";
import { EventRow, type Ev } from "./events";
import { KpTab, type Mentionable } from "./KpTab";

type Tab = "map" | "broadcast" | "kp" | "chat" | "sheet";

function StatusBar({ status }: { status: Schemas["StatusOut"] | null }) {
  const { t, lang } = useI18n();
  if (!status) return null;
  const phase = status.game_status === "ended" ? t("status.ended") : status.phase ? t(`status.phase.${status.phase}`) : t("status.not_started");
  return (
    <div className="sk-statusbar">
      <span>{t("status.round", { round: String(status.round) })}</span>
      <span>{formatGameTime(status.start_time, status.game_minutes, lang)}</span>
      <span>{phase}</span>
      <span>{t("status.submitted", { done: String(status.submitted), total: String(status.total) })}</span>
      <LangSwitch onChange={(l) => void api.POST("/api/lang", { body: { lang: l } })} />
    </div>
  );
}

function MapTab({
  map,
  scene,
  onPick,
  onRename,
}: {
  map: DisplayMap | null;
  scene: Schemas["SceneOut"] | null;
  onPick: (p: Pick) => void;
  onRename: (ref: string, label: string, note: string) => Promise<void>;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const markers = useMemo<MarkerView[]>(() => {
    if (!scene) return [];
    const out = new Map<string, MarkerView>();
    for (const e of scene.entities) {
      if (e.pos) out.set(e.ref, { ref: e.ref, label: e.name, lon: e.pos.lon, lat: e.pos.lat, z: e.pos.z, own: true });
      for (const p of e.presence) out.set(p.ref, { ref: p.ref, label: p.label, lon: p.pos.lon, lat: p.pos.lat, z: p.pos.z, own: false });
    }
    return [...out.values()];
  }, [scene]);
  if (!map || !scene) return <p>{t("common.loading")}</p>;
  return (
    <div>
      <MapView map={map} markers={markers} changes={scene.map_changes} onPick={onPick} height="55vh" />
      <p className="sk-hint">{t("play.map_hint")}</p>
      {scene.entities.map((e) => (
        <div key={e.ref} className="sk-card">
          <strong>{e.name}</strong>
          <div className="sk-hint">{t("play.presence")}</div>
          {e.presence.length === 0 && <div className="sk-hint">{t("play.nobody")}</div>}
          <ul>
            {e.presence.map((p) => (
              <li key={p.ref}>
                <button className="sk-link" onClick={() => onPick({ kind: "entity", ref: p.ref, label: p.label })}>
                  @{p.label}
                </button>
                {p.note && <span className="sk-hint"> {p.note}</span>}
                <button className="sk-link" onClick={() => { setEditing(p.ref); setLabel(p.label); setNote(p.note); }}>
                  {t("play.rename")}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {scene.seen.length > 0 && (
        <div className="sk-card">
          <strong>{t("play.seen")}</strong>
          <ul>
            {scene.seen.map((s) => (
              <li key={s.ref}>
                <button className="sk-link" onClick={() => onPick({ kind: "entity", ref: s.ref, label: s.label })}>
                  @{s.label}
                </button>
                {s.note && <span className="sk-hint"> {s.note}</span>}
                <button className="sk-link" onClick={() => { setEditing(s.ref); setLabel(s.label); setNote(s.note); }}>
                  {t("play.rename")}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {editing && (
        <div className="sk-card">
          <label>
            {t("play.handle_label")}
            <input value={label} onChange={(e) => setLabel(e.target.value)} />
          </label>
          <label>
            {t("play.handle_note")}
            <input value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <button onClick={() => void onRename(editing, label, note).then(() => setEditing(null))}>{t("common.save")}</button>
          <button className="sk-link" onClick={() => setEditing(null)}>
            {t("common.cancel")}
          </button>
        </div>
      )}
    </div>
  );
}

function BroadcastTab({ events, onQuote, onChanged }: { events: Ev[]; onQuote: (s: number) => void; onChanged: () => void }) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [anon, setAnon] = useState(false);
  const act = useAction();
  const list = events.filter((e) => e.type === "broadcast" || e.type === "round_opened");
  return (
    <div>
      <div className="sk-log">
        {list.map((e) => (
          <EventRow key={e.seq} e={e} onQuote={e.type === "broadcast" ? onQuote : undefined} />
        ))}
      </div>
      <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} />
      <div className="sk-row">
        <label className="sk-inline">
          <input type="checkbox" checked={anon} onChange={(e) => setAnon(e.target.checked)} /> {t("broadcast.anonymous")}
        </label>
        <button
          disabled={!text.trim() || act.busy}
          onClick={() =>
            void act.run(async () => {
              await call(api.POST("/api/broadcast", { body: { text, anonymous: anon } }));
              setText("");
              onChanged();
            })
          }
        >
          {t("broadcast.send")}
        </button>
      </div>
      <p className="sk-hint">{t("broadcast.hint")}</p>
      <ErrorBox error={act.error} />
    </div>
  );
}

function ChatTab() {
  const { t } = useI18n();
  const peers = usePoll(() => call(api.GET("/api/chat/peers")), 60_000);
  const msgs = usePoll(() => call(api.GET("/api/chat", { params: { query: { since: 0 } } })), 10_000);
  const [peer, setPeer] = useState<string>("");
  const [text, setText] = useState("");
  const act = useAction();
  const conv = (msgs.data ?? []).filter((m) => m.sender === peer || m.recipient === peer);
  return (
    <div>
      <p className="sk-hint">{t("chat.hint")}</p>
      <select value={peer} onChange={(e) => setPeer(e.target.value)}>
        <option value="">{t("chat.pick_peer")}</option>
        {(peers.data ?? []).map((p) => (
          <option key={p.player_id} value={p.player_id}>
            {p.display_name}
          </option>
        ))}
      </select>
      {peer && (
        <>
          <div className="sk-log">
            {conv.map((m) => (
              <div key={m.id} className={m.mine ? "sk-event mine" : "sk-event"}>
                <span className="text">{m.text}</span>
              </div>
            ))}
          </div>
          <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} />
          <button
            disabled={!text.trim() || act.busy}
            onClick={() =>
              void act.run(async () => {
                await call(api.POST("/api/chat", { body: { to: peer, text } }));
                setText("");
                void msgs.refresh();
              })
            }
          >
            {t("chat.send")}
          </button>
          <ErrorBox error={act.error} />
        </>
      )}
    </div>
  );
}

function SheetTab() {
  const { t } = useI18n();
  const sheets = usePoll(() => call(api.GET("/api/sheets")), 30_000);
  const rules = usePoll(() => call(api.GET("/api/rules")), 600_000);
  const [hist, setHist] = useState<string | null>(null);
  return (
    <div>
      {(sheets.data ?? []).map((s) => {
        const tpl = ((rules.data?.templates ?? []) as unknown as Schemas["EntityTemplate"][]).find((x) => x.name === s.template);
        const fdef = (k: string) => tpl?.fields?.find((f) => f.name === k);
        const sheet = s.sheet as { name?: string; fields?: Record<string, unknown>; groups?: Record<string, { name: string; description?: string }[]>; statuses?: { tag: string }[]; items?: { name: string; qty?: number }[] };
        return (
          <div key={s.entity_id} className="sk-card">
            <h3>{sheet.name}</h3>
            <table className="sk-table">
              <tbody>
                {Object.entries(sheet.fields ?? {}).map(([k, v]) => (
                  <tr key={k}>
                    <th>{fdef(k)?.label || k}</th>
                    <td>
                      {String(v)}
                      {fdef(k)?.description && <div className="sk-hint">{fdef(k)?.description}</div>}
                    </td>
                  </tr>
                ))}
                {s.derived.map((d) => (
                  <tr key={d.name}>
                    <th>{d.name}</th>
                    <td>{Math.round(d.value * 100) / 100}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {Object.entries(sheet.groups ?? {}).map(([g, entries]) => (
              <div key={g}>
                <strong>{tpl?.groups?.find((x) => x.name === g)?.label || g}</strong>
                <ul>
                  {entries.map((en, i) => (
                    <li key={i}>
                      {en.name} {en.description}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            {(sheet.statuses ?? []).length > 0 && (
              <div>
                <strong>{t("sheet.statuses")}</strong> {(sheet.statuses ?? []).map((x) => x.tag).join(", ")}
              </div>
            )}
            <button className="sk-link" onClick={() => setHist(hist === s.entity_id ? null : s.entity_id)}>
              {t("sheet.history")} ({s.history.length})
            </button>
            {hist === s.entity_id && (
              <ul className="sk-hint">
                {s.history.map((h, i) => (
                  <li key={i}>
                    {t("sheet.change", { round: String(h.round_no), path: h.path, old: JSON.stringify(h.old), new: JSON.stringify(h.new) })}
                    {h.source_seq ? ` #${h.source_seq}` : ""} · {t(`sheet.source.${h.source_kind}`)}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** /play：主界面，五个标签页。每 10 秒轮询一次。 */
export function PlayPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("kp");
  const [draft, setDraft] = useState("");
  const [quotes, setQuotes] = useState<number[]>([]);
  const status = usePoll(() => call(api.GET("/api/status")), 10_000);
  const events = usePoll(() => call(api.GET("/api/events", { params: { query: { since: 0 } } })), 10_000);
  const scene = usePoll(() => call(api.GET("/api/scene")), 10_000);
  const map = usePoll(async () => (await call(api.GET("/api/map"))) as unknown as DisplayMap, 3_600_000);
  const err = useAction();
  const evs = events.data ?? [];
  const refresh = () => {
    void status.refresh();
    void events.refresh();
    void scene.refresh();
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

  if (status.error && !status.data) {
    return (
      <main className="sk-page">
        <p>{t("join.invalid")}</p>
      </main>
    );
  }

  const onPick = (p: Pick) =>
    void err.run(async () => {
      if (p.kind === "entity") setDraft(`${draft}@[${p.label}](${p.ref}) `);
      else if (p.kind === "feature") setDraft(`${draft}@[${p.name || p.id}](feature:${p.id}) `);
      else {
        const m = await call(api.GET("/api/map/project", { params: { query: { lon: p.lon, lat: p.lat } } }));
        setDraft(`${draft}@[${t("kp.a_point")}](point:${m.x},${m.y},0) `);
      }
      setTab("kp");
    });

  return (
    <main className="sk-page sk-play">
      <StatusBar status={status.data} />
      <Tabs
        tabs={[
          { key: "map", label: t("play.tab.map") },
          { key: "broadcast", label: t("play.tab.broadcast") },
          { key: "kp", label: t("play.tab.kp") },
          { key: "chat", label: t("play.tab.chat") },
          { key: "sheet", label: t("play.tab.sheet") },
        ]}
        active={tab}
        onChange={setTab}
      />
      <ErrorBox error={err.error} />
      {tab === "map" && (
        <MapTab
          map={map.data}
          scene={scene.data}
          onPick={onPick}
          onRename={async (ref, label, note) => {
            await err.run(() => call(api.PATCH("/api/handles/{ref}", { params: { path: { ref } }, body: { label, note } })));
            void scene.refresh();
          }}
        />
      )}
      {tab === "broadcast" && <BroadcastTab events={evs} onQuote={(s) => setQuotes(Array.from(new Set([...quotes, s])))} onChanged={refresh} />}
      {tab === "kp" && (
        <KpTab
          events={evs}
          status={status.data}
          draft={draft}
          setDraft={setDraft}
          quotes={quotes}
          setQuotes={setQuotes}
          mentionables={mentionables}
          onChanged={refresh}
        />
      )}
      {tab === "chat" && <ChatTab />}
      {tab === "sheet" && <SheetTab />}
    </main>
  );
}
