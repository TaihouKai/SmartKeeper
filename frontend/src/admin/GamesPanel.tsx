import { useEffect, useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { MapView, type DisplayMap } from "../map";
import { ErrorBox, MarkdownView, Section } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";

/** “资料”面板：上传、替换、预览剧本和地图文件。 */
export function MaterialsPanel() {
  const { t } = useI18n();
  const mats = usePoll(() => call(api.GET("/api/admin/materials")), 600_000);
  const [scenario, setScenario] = useState<Schemas["ScenarioOut"] | null>(null);
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<DisplayMap | null>(null);
  const act = useAction();
  const open = (n: string) => void act.run(async () => setScenario(await call(api.GET("/api/admin/materials/scenarios/{name}", { params: { path: { name: n } } }))));
  const saveScenario = () =>
    void act.run(async () => {
      if (!scenario) return;
      for (const part of ["public", "kp"] as const) {
        await call(api.PUT("/api/admin/materials/scenarios/{name}/{part}", { params: { path: { name: scenario.name, part } }, body: { text: part === "public" ? scenario.public : scenario.kp } }));
      }
      void mats.refresh();
    });
  const uploadMap = (file: File, id: string) =>
    void act.run(async () => {
      await call(api.PUT("/api/admin/materials/maps/{map_id}", { params: { path: { map_id: id } }, body: { text: await file.text() } }));
      void mats.refresh();
    });
  return (
    <Section title={t("admin.panel.materials")}>
      <ErrorBox error={act.error} />
      <div className="sk-card">
        <h3>{t("materials.scenarios")}</h3>
        {(mats.data?.scenarios ?? []).map((s) => (
          <button key={s} className="sk-link" onClick={() => open(s)}>{s}</button>
        ))}
        <div className="sk-row">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("materials.new_name")} />
          <button disabled={!name} onClick={() => setScenario({ name, public: "---\nstart_time: \"2030-01-01T20:00\"\n---\n", kp: "---\nnpcs: []\n---\n" })}>{t("materials.new_scenario")}</button>
        </div>
        {scenario && (
          <div>
            <h4>{scenario.name}</h4>
            <label>{t("materials.public")}<textarea rows={10} value={scenario.public} onChange={(e) => setScenario({ ...scenario, public: e.target.value })} /></label>
            <label>{t("materials.kp")}<textarea rows={10} value={scenario.kp} onChange={(e) => setScenario({ ...scenario, kp: e.target.value })} /></label>
            <button className="sk-primary" onClick={saveScenario}>{t("common.save")}</button>
            <details>
              <summary>{t("materials.preview")}</summary>
              <MarkdownView text={scenario.public} />
            </details>
          </div>
        )}
      </div>
      <div className="sk-card">
        <h3>{t("materials.maps")}</h3>
        {(mats.data?.maps ?? []).map((m) => (
          <button key={m} className="sk-link" onClick={() => void act.run(async () => setPreview((await call(api.GET("/api/admin/materials/maps/{map_id}", { params: { path: { map_id: m } } }))) as unknown as DisplayMap))}>
            {m}
          </button>
        ))}
        <MapUpload onUpload={uploadMap} />
        {preview && <MapView map={preview} markers={[]} changes={[]} height="40vh" />}
      </div>
    </Section>
  );
}

function MapUpload({ onUpload }: { onUpload: (f: File, id: string) => void }) {
  const { t } = useI18n();
  const [id, setId] = useState("");
  return (
    <div className="sk-row">
      <input value={id} onChange={(e) => setId(e.target.value)} placeholder={t("materials.map_id")} />
      <input type="file" accept=".geojson,.json" disabled={!id} onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0], id)} />
    </div>
  );
}

function NewGame({ onCreated }: { onCreated: (id: string) => void }) {
  const { t } = useI18n();
  const packs = usePoll(() => call(api.GET("/api/admin/rulepacks")), 600_000);
  const mats = usePoll(() => call(api.GET("/api/admin/materials")), 600_000);
  const [form, setForm] = useState({ name: "", pack: "", map: "", scenario: "" });
  const act = useAction();
  const options = (packs.data ?? []).flatMap((p) => p.versions.map((v) => ({ key: `${p.pack_id}@${v}`, label: `${p.name} v${v}` })));
  return (
    <div className="sk-card">
      <h3>{t("games.new")}</h3>
      <label>{t("games.name")}<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
      <label>{t("games.rulepack")}
        <select value={form.pack} onChange={(e) => setForm({ ...form, pack: e.target.value })}>
          <option value="" />
          {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
        </select>
      </label>
      <label>{t("games.map")}
        <select value={form.map} onChange={(e) => setForm({ ...form, map: e.target.value })}>
          <option value="" />
          {(mats.data?.maps ?? []).map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </label>
      <label>{t("games.scenario")}
        <select value={form.scenario} onChange={(e) => setForm({ ...form, scenario: e.target.value })}>
          <option value="" />
          {(mats.data?.scenarios ?? [])
            .filter((m) => {
              // 剧本属于一套规则书：只列这套规则书的（和没写属于哪套的）
              const book = mats.data?.scenario_rulebooks?.[m] ?? "";
              const pack = (packs.data ?? []).find((p) => p.pack_id === form.pack.split("@")[0]);
              return !book || !pack || book === pack.name;
            })
            .map((m) => <option key={m} value={m}>{m}{mats.data?.scenario_rulebooks?.[m] ? `（${mats.data.scenario_rulebooks[m]}）` : ""}</option>)}
        </select>
      </label>
      <button
        className="sk-primary"
        disabled={!form.name || !form.pack || !form.scenario || act.busy}
        onClick={() =>
          void act.run(async () => {
            const [rulepack_id = "", v = "1"] = form.pack.split("@");
            const g = await call(api.POST("/api/admin/games", { body: { name: form.name, rulepack_id, rulepack_version: Number(v), map_id: form.map || null, scenario: form.scenario, settings: { web_search: true, kp_language: "zh", min_round_seconds: 0, lobby: true } } }));
            onCreated(g.id);
          })
        }
      >
        {t("games.create")}
      </button>
      <ErrorBox error={act.error} />
    </div>
  );
}

function Settings({ game, onSaved }: { game: Schemas["Game"]; onSaved: () => void }) {
  const { t } = useI18n();
  const [s, setS] = useState(game.settings);
  const act = useAction();
  useEffect(() => {
    setS(game.settings);
  }, [game.settings]);
  return (
    <div className="sk-card">
      <h3>{t("games.settings")}</h3>
      <label className="sk-inline"><input type="checkbox" checked={s.lobby ?? true} onChange={(e) => setS({ ...s, lobby: e.target.checked })} /> {t("games.lobby")}</label>
      <label className="sk-inline"><input type="checkbox" checked={s.web_search ?? true} onChange={(e) => setS({ ...s, web_search: e.target.checked })} /> {t("games.web_search")}</label>
      <label>{t("games.kp_language")}
        <select value={s.kp_language ?? "zh"} onChange={(e) => setS({ ...s, kp_language: e.target.value })}>
          <option value="zh">{t("lang.zh")}</option>
          <option value="en">{t("lang.en")}</option>
        </select>
      </label>
      <label>{t("games.min_round")}<input type="number" min={0} value={s.min_round_seconds ?? 0} onChange={(e) => setS({ ...s, min_round_seconds: Math.max(0, Number(e.target.value) || 0) })} /></label>
      <p className="sk-hint">{t("games.min_round_hint")}</p>
      <label>{t("games.player_webhook")}<input value={s.player_webhook ?? ""} onChange={(e) => setS({ ...s, player_webhook: e.target.value || null })} /></label>
      <label>{t("games.admin_webhook")}<input value={s.admin_webhook ?? ""} onChange={(e) => setS({ ...s, admin_webhook: e.target.value || null })} /></label>
      <button onClick={() => void act.run(async () => { await call(api.PATCH("/api/admin/games/{game_id}", { params: { path: { game_id: game.id } }, body: { settings: s } })); onSaved(); })}>{t("common.save")}</button>
      <ErrorBox error={act.error} />
    </div>
  );
}

/** “局管理”和“回合”面板。 */
export function GamesPanel({ selected, onSelect }: { selected: string | null; onSelect: (id: string) => void }) {
  const { t } = useI18n();
  const games = usePoll(() => call(api.GET("/api/admin/games")), 30_000);
  const detail = usePoll(async () => (selected ? call(api.GET("/api/admin/games/{game_id}", { params: { path: { game_id: selected } } })) : null), 10_000, [selected]);
  const [invite, setInvite] = useState("");
  const [links, setLinks] = useState<{ name: string; url: string }[]>([]);
  const act = useAction();
  const d = detail.data;
  const gid = selected ?? "";
  const refresh = () => { void detail.refresh(); void games.refresh(); };
  return (
    <Section title={t("admin.panel.games")}>
      <div className="sk-card">
        {(games.data ?? []).map((g) => (
          <button key={g.id} className={g.id === selected ? "sk-chip active" : "sk-chip"} onClick={() => onSelect(g.id)}>
            {g.name} · {t(`games.status.${g.status}`)}
          </button>
        ))}
      </div>
      <NewGame onCreated={(id) => { onSelect(id); void games.refresh(); }} />
      <ErrorBox error={act.error} />
      {d && (
        <>
          <Settings game={d.game} onSaved={refresh} />
          {!d.searchable && <p className="sk-hint">{t("games.no_search")}</p>}
          <div className="sk-card">
            <h3>{t("games.players")}</h3>
            <table className="sk-table">
              <tbody>
                {d.players.map((p) => (
                  <tr key={p.id} className={p.active ? "" : "inactive"}>
                    <td>{p.display_name}</td>
                    <td>{t(`join.status.${p.character_status}`)}</td>
                    <td>{d.game.status === "running" ? t(p.submitted ? "games.submitted" : "games.waiting") : ""}</td>
                    <td>
                      {p.active && <button className="sk-link" onClick={() => void act.run(async () => { await call(api.DELETE("/api/admin/games/{game_id}/invites/{player_id}", { params: { path: { game_id: gid, player_id: p.id } } })); refresh(); })}>{t("games.revoke")}</button>}
                      {p.character_status === "submitted" && <button className="sk-link" onClick={() => void act.run(async () => { await call(api.POST("/api/admin/games/{game_id}/characters/{player_id}/review", { params: { path: { game_id: gid, player_id: p.id } } })); })}>{t("games.rereview")}</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="sk-row">
              <input value={invite} onChange={(e) => setInvite(e.target.value)} placeholder={t("games.player_name")} />
              <button disabled={!invite} onClick={() => void act.run(async () => {
                const r = await call(api.POST("/api/admin/games/{game_id}/invites", { params: { path: { game_id: gid } }, body: { display_name: invite } }));
                setLinks([...links, { name: invite, url: r.url }]);
                setInvite("");
                refresh();
              })}>{t("games.invite")}</button>
            </div>
            {links.map((l) => (
              <div key={l.url} className="sk-invite">
                {l.name}: <code>{l.url}</code>
              </div>
            ))}
            {links.length > 0 && <p className="sk-hint">{t("games.invite_once")}</p>}
          </div>
          <div className="sk-card">
            <h3>{t("games.lifecycle")}</h3>
            <p>{t(`games.status.${d.game.status}`)} · {d.round ? t("status.round", { round: String(d.round.no) }) + " · " + t(`status.phase.${d.round.status}`) : ""}</p>
            {d.game.status === "characters" && (
              <button className="sk-primary" disabled={d.opening?.state === "running"} onClick={() => void act.run(async () => { await call(api.PATCH("/api/admin/games/{game_id}", { params: { path: { game_id: gid } }, body: { action: "start" } })); refresh(); })}>{t("games.start")}</button>
            )}
            {d.opening?.state === "running" && <p className="sk-hint">{t("games.opening_running")}</p>}
            {d.opening?.state === "failed" && (
              <div className="sk-error">
                <p>{t("games.opening_failed")}</p>
                <pre className="sk-code">{d.opening.error}</pre>
              </div>
            )}
            {d.game.status === "running" && d.round?.status === "collecting" && (
              <button onClick={() => void act.run(async () => { await call(api.POST("/api/admin/games/{game_id}/round/close", { params: { path: { game_id: gid } } })); refresh(); })}>{t("games.force_close")}</button>
            )}
            {d.round?.status === "review" && (
              <button onClick={() => void act.run(async () => { await call(api.POST("/api/admin/games/{game_id}/round/rerun", { params: { path: { game_id: gid } } })); refresh(); })}>{t("games.rerun")}</button>
            )}
            {d.game.status !== "ended" && (
              <button className="sk-link" onClick={() => void act.run(async () => { await call(api.PATCH("/api/admin/games/{game_id}", { params: { path: { game_id: gid } }, body: { action: "end" } })); refresh(); })}>{t("games.end")}</button>
            )}
          </div>
        </>
      )}
    </Section>
  );
}
