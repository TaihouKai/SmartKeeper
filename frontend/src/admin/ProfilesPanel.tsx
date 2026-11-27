import { useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, Section } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";

type Profile = Schemas["LLMProfile"];

const EMPTY: Profile = { id: "", name: "", judge_provider: "", judge_model: "", writer_provider: "", writer_model: "" };

/** 一套模型的简短说明：裁定用的 / 其余调用用的。 */
export function profileSummary(p: Profile): string {
  const judge = `${p.judge_provider}/${p.judge_model}`;
  const writer = `${p.writer_provider}/${p.writer_model}`;
  return judge === writer ? judge : `${judge} + ${writer}`;
}

/** 这局用哪套模型的下拉菜单。空的是服务器配置的默认那套。 */
export function ProfileSelect({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const { t } = useI18n();
  const data = usePoll(() => call(api.GET("/api/admin/llm-profiles")), 600_000);
  const d = data.data;
  return (
    <label>
      {t("profiles.choose")}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t("profiles.default")}{d ? `（${profileSummary(d.default)}）` : ""}</option>
        {(d?.profiles ?? []).map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}（{profileSummary(p)}）
          </option>
        ))}
        {/* 选的那套被删了：还显示出来，免得看着像默认 */}
        {d && value && !d.profiles.some((p) => p.id === value) && <option value={value}>{t("profiles.missing")}</option>}
      </select>
    </label>
  );
}

function Editor({ profile, providers, onDone }: { profile: Profile; providers: string[]; onDone: () => void }) {
  const { t } = useI18n();
  const [p, setP] = useState(profile);
  const act = useAction();
  const slot = (kind: "judge" | "writer") => {
    const provider = kind === "judge" ? "judge_provider" : "writer_provider";
    const model = kind === "judge" ? "judge_model" : "writer_model";
    return (
      <div className="sk-row">
        <label>{t(`profiles.${kind}`)}
          <select value={p[provider]} onChange={(e) => setP({ ...p, [provider]: e.target.value })}>
            <option value="" />
            {providers.map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
        </label>
        <label>{t("profiles.model")}<input value={p[model]} onChange={(e) => setP({ ...p, [model]: e.target.value })} /></label>
      </div>
    );
  };
  return (
    <div className="sk-card">
      <label>{t("profiles.name")}<input value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} /></label>
      {slot("judge")}
      <p className="sk-hint">{t("profiles.judge_hint")}</p>
      {slot("writer")}
      <p className="sk-hint">{t("profiles.writer_hint")}</p>
      <div className="sk-row">
        <button className="sk-primary" disabled={act.busy} onClick={() => void act.run(async () => { await call(api.POST("/api/admin/llm-profiles", { body: p })); onDone(); })}>
          {t("common.save")}
        </button>
        <button onClick={onDone}>{t("common.cancel")}</button>
      </div>
      <ErrorBox error={act.error} />
    </div>
  );
}

/** “模型配置”面板：几套模型选择（比如正式版、测试版），开局时选一套。 */
export function ProfilesPanel() {
  const { t } = useI18n();
  const data = usePoll(() => call(api.GET("/api/admin/llm-profiles")), 600_000);
  const [editing, setEditing] = useState<Profile | null>(null);
  const act = useAction();
  const d = data.data;
  const done = () => { setEditing(null); void data.refresh(); };
  return (
    <Section title={t("admin.panel.profiles")}>
      <p className="sk-hint">{t("profiles.hint")}</p>
      <ErrorBox error={act.error} />
      <div className="sk-card">
        <table className="sk-table">
          <tbody>
            {d && (
              <tr>
                <td>{t("profiles.default")}</td>
                <td>{profileSummary(d.default)}</td>
                <td className="sk-hint">{t("profiles.default_hint")}</td>
              </tr>
            )}
            {(d?.profiles ?? []).map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td>{profileSummary(p)}</td>
                <td>
                  <button className="sk-link" onClick={() => setEditing(p)}>{t("profiles.edit")}</button>
                  <button className="sk-link" onClick={() => void act.run(async () => { await call(api.DELETE("/api/admin/llm-profiles/{profile_id}", { params: { path: { profile_id: p.id } } })); void data.refresh(); })}>
                    {t("common.remove")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!editing && <button onClick={() => setEditing(EMPTY)}>{t("profiles.new")}</button>}
      </div>
      {editing && d && <Editor key={editing.id || "new"} profile={editing} providers={d.providers} onDone={done} />}
    </Section>
  );
}
