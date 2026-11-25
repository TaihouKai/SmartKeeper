import { useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";

export type LibraryChar = Schemas["LibraryCharacter"];
/** 从角色库载入的角色：之后提交时可以更新它（要它的密码）。 */
export type Origin = { id: string; name: string; summary: string; password: string | null; locked: boolean };

/** 选角色：这套规则书的角色库（别人建的也能用，设了密码的要密码），或者新建一个。 */
export function CharacterPicker({ onPick, onNew }: { onPick: (sheets: unknown, origin: Origin) => void; onNew: () => void }) {
  const { t } = useI18n();
  const list = usePoll(() => call(api.GET("/api/library")), 60_000);
  const [asking, setAsking] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const act = useAction();
  const open = (c: LibraryChar, pw: string | null) =>
    void act.run(async () => {
      const full = await call(api.POST("/api/library/{char_id}/open", { params: { path: { char_id: c.id } }, body: { password: pw } }));
      onPick(full.sheets, { id: c.id, name: c.name, summary: c.summary ?? "", password: pw, locked: c.locked ?? false });
    });
  const chars = list.data ?? [];
  return (
    <div className="sk-card lib-pick">
      <div className="lib-head">
        <strong>{t("lib.pick_title")}</strong>
        <button type="button" className="sk-primary" onClick={onNew}>
          {t("lib.new")}
        </button>
      </div>
      <p className="sk-hint">{t("lib.pick_hint")}</p>
      {list.data && chars.length === 0 && <p className="sk-hint">{t("lib.empty")}</p>}
      <ul className="lib-list">
        {chars.map((c) => (
          <li key={c.id}>
            <div className="lib-main">
              <strong>
                {c.locked && <span title={t("lib.locked")}>🔒 </span>}
                {c.name}
              </strong>
              <span className="sk-hint"> {t("lib.by", { who: c.created_by ?? "" })}</span>
              {c.summary && <p className="lib-summary">{c.summary}</p>}
            </div>
            {asking === c.id ? (
              <span className="lib-pw">
                <input type="password" autoFocus value={password} placeholder={t("lib.password")} onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => e.key === "Enter" && open(c, password)} />
                <button type="button" className="sk-primary" onClick={() => open(c, password)}>
                  {t("lib.use")}
                </button>
                <button type="button" className="sk-link" onClick={() => setAsking(null)}>
                  {t("common.cancel")}
                </button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => {
                  if (c.locked) {
                    setAsking(c.id);
                    setPassword("");
                  } else open(c, null);
                }}
              >
                {t("lib.use")}
              </button>
            )}
          </li>
        ))}
      </ul>
      <ErrorBox error={act.error} />
    </div>
  );
}

/** 提交时怎么处理角色库：存成新角色、更新载入的那个、或者不存。 */
export type LibrarySave = { mode: "new" | "update" | "none"; name: string; summary: string; password: string; newPassword: string };

export function initialSave(origin: Origin | null): LibrarySave {
  return origin
    ? { mode: "none", name: origin.name, summary: origin.summary, password: "", newPassword: "" }
    : { mode: "new", name: "", summary: "", password: "", newPassword: "" };
}

/** 提交前的角色库设置（放在建卡页底部）。 */
export function LibraryBox({ origin, value, onChange }: { origin: Origin | null; value: LibrarySave; onChange: (v: LibrarySave) => void }) {
  const { t } = useI18n();
  const set = (patch: Partial<LibrarySave>) => onChange({ ...value, ...patch });
  return (
    <div className="sk-card lib-box">
      <strong>{t("lib.box_title")}</strong>
      <div className="lib-modes">
        <label>
          <input type="radio" checked={value.mode === "new"} onChange={() => set({ mode: "new" })} /> {t("lib.save_new")}
        </label>
        {origin && (
          <label>
            <input type="radio" checked={value.mode === "update"} onChange={() => set({ mode: "update" })} /> {t("lib.save_update", { name: origin.name })}
          </label>
        )}
        <label>
          <input type="radio" checked={value.mode === "none"} onChange={() => set({ mode: "none" })} /> {t("lib.save_none")}
        </label>
      </div>
      {value.mode !== "none" && (
        <div className="lib-fields">
          <label>
            {t("lib.name")}
            <input value={value.name} placeholder={t("lib.name_ph")} onChange={(e) => set({ name: e.target.value })} />
          </label>
          <label>
            {t("lib.summary")}
            <textarea rows={2} value={value.summary} placeholder={t("lib.summary_ph")} onChange={(e) => set({ summary: e.target.value })} />
          </label>
          {value.mode === "new" ? (
            <label>
              {t("lib.password")}
              <input type="password" value={value.password} placeholder={t("lib.password_ph")} onChange={(e) => set({ password: e.target.value })} />
            </label>
          ) : (
            <label>
              {t("lib.new_password")}
              <input type="password" value={value.newPassword} placeholder={t("lib.new_password_ph")} onChange={(e) => set({ newPassword: e.target.value })} />
            </label>
          )}
        </div>
      )}
    </div>
  );
}

/** 提交成功以后按设置存进角色库。 */
export async function saveToLibrary(sheets: unknown, origin: Origin | null, v: LibrarySave): Promise<void> {
  if (v.mode === "none") return;
  const body = { sheets: sheets as never, name: v.name, summary: v.summary };
  if (v.mode === "update" && origin) {
    await call(
      api.PUT("/api/library/{char_id}", {
        params: { path: { char_id: origin.id } },
        body: { ...body, password: origin.password, new_password: v.newPassword ? v.newPassword : null },
      }),
    );
    return;
  }
  await call(api.POST("/api/library", { body: { ...body, password: v.password || null } }));
}
