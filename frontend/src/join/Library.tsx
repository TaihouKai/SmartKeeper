import { useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";
import type { FormBackend } from "./formBackend";

export type LibraryChar = Schemas["LibraryCharacter"];
/** 从角色库载入的角色：之后提交时可以更新它（要它的密码）。 */
export type Origin = { id: string; name: string; summary: string; password: string | null; locked: boolean; own?: boolean };

/** 选角色：这套规则书的角色库（别人建的也能用，设了密码的要密码），或者新建一个。 */
/** me：自己的昵称；自己建的角色载入以后默认接着更新它 */
export function CharacterPicker({ onPick, onNew, me = "" }: { onPick: (sheets: unknown, origin: Origin) => void; onNew: () => void; me?: string }) {
  const { t } = useI18n();
  const list = usePoll(() => call(api.GET("/api/library")), 60_000);
  const [asking, setAsking] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const act = useAction();
  const open = (c: LibraryChar, pw: string | null) =>
    void act.run(async () => {
      const full = await call(api.POST("/api/library/{char_id}/open", { params: { path: { char_id: c.id } }, body: { password: pw } }));
      onPick(full.sheets, { id: c.id, name: c.name, summary: c.summary ?? "", password: pw, locked: c.locked ?? false, own: Boolean(me) && c.created_by === me });
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

/** 从角色库载入的一套卡：只留这套规则书要玩家建的卡，缺的部分补齐。 */
export function normalizeSheets(sheets: unknown, entities: readonly { template: string }[]): unknown[] {
  const wanted = new Set(entities.map((x) => x.template));
  return (Array.isArray(sheets) ? (sheets as { template: string; sheet: Record<string, unknown> }[]) : [])
    .filter((x) => wanted.has(x.template))
    .map((x) => ({ template: x.template, sheet: { name: "", fields: {}, groups: {}, preset_fields: {}, ...(x.sheet ?? {}) } }));
}

/** 记住正在编辑的是角色库里的哪个角色（刷新页面以后还能存回去）。不记密码。 */
const ORIGIN_KEY = "sk.libOrigin.";

export function loadOrigin(playerId: string): Origin | null {
  try {
    const raw = window.localStorage.getItem(ORIGIN_KEY + playerId);
    const o = raw ? (JSON.parse(raw) as Origin) : null;
    return o && typeof o.id === "string" ? { ...o, password: null } : null;
  } catch {
    return null;
  }
}

export function rememberOrigin(playerId: string, o: Origin | null): void {
  try {
    if (o) window.localStorage.setItem(ORIGIN_KEY + playerId, JSON.stringify({ ...o, password: null }));
    else window.localStorage.removeItem(ORIGIN_KEY + playerId);
  } catch {
    // 存不了（隐私模式等）就只在这一页里记着
  }
}

/** 角色库怎么存：存成新角色、更新正在编辑的那个、或者不存。current 是更新带锁的角色要的密码（载入时输过的不用再输）。 */
export type LibrarySave = { mode: "new" | "update" | "none"; name: string; summary: string; password: string; newPassword: string; current: string; author: string };

export function initialSave(origin: Origin | null, bookMode = false): LibrarySave {
  const blank = { password: "", newPassword: "", current: "", author: bookMode ? lastAuthor() : "" };
  if (!origin) return { mode: "new", name: "", summary: "", ...blank };
  // 自己存进去的、在规则书下打开来改的，默认接着更新它；局里载入别人的默认不动它
  return { mode: origin.own || bookMode ? "update" : "none", name: origin.name, summary: origin.summary, ...blank };
}

/** 不进局建角色时写的作者名：记在浏览器里，下次不用再填。 */
const AUTHOR_KEY = "sk.libAuthor";

function lastAuthor(): string {
  try {
    return window.localStorage.getItem(AUTHOR_KEY) ?? "";
  } catch {
    return "";
  }
}

function rememberAuthor(name: string): void {
  try {
    window.localStorage.setItem(AUTHOR_KEY, name);
  } catch {
    // 记不住就下次再填
  }
}

/** 建卡页底部的角色库：怎么存、名字、简介、密码；随时可以“现在存进角色库”，提交给这一局时也按这里的设置存。 */
export function LibraryBox({
  origin,
  value,
  onChange,
  onSaveNow,
  busy,
  savedAt,
  bookMode = false,
}: {
  origin: Origin | null;
  value: LibrarySave;
  onChange: (v: LibrarySave) => void;
  onSaveNow: () => void;
  busy: boolean;
  savedAt: string | null;
  /** 在规则书下编辑：一定要存（没有“不存”），存的按钮在底栏 */
  bookMode?: boolean;
}) {
  const { t } = useI18n();
  const set = (patch: Partial<LibrarySave>) => onChange({ ...value, ...patch });
  const needCurrent = value.mode === "update" && origin !== null && origin.locked && !origin.password;
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
        {!bookMode && (
          <label>
            <input type="radio" checked={value.mode === "none"} onChange={() => set({ mode: "none" })} /> {t("lib.save_none")}
          </label>
        )}
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
          {bookMode && value.mode === "new" && (
            <label>
              {t("lib.author")}
              <input value={value.author} placeholder={t("lib.author_ph")} onChange={(e) => set({ author: e.target.value })} />
            </label>
          )}
          {value.mode === "new" ? (
            <label>
              {t("lib.password")}
              <input type="password" value={value.password} placeholder={t("lib.password_ph")} onChange={(e) => set({ password: e.target.value })} />
            </label>
          ) : (
            <>
              {needCurrent && (
                <label>
                  {t("lib.current_password")}
                  <input type="password" value={value.current} placeholder={t("lib.current_password_ph")} onChange={(e) => set({ current: e.target.value })} />
                </label>
              )}
              <label>
                {t("lib.new_password")}
                <input type="password" value={value.newPassword} placeholder={t("lib.new_password_ph")} onChange={(e) => set({ newPassword: e.target.value })} />
              </label>
            </>
          )}
          <div className="sk-row">
            {!bookMode && (
              <button type="button" disabled={busy} onClick={onSaveNow}>
                {t(value.mode === "update" ? "lib.save_now_update" : "lib.save_now")}
              </button>
            )}
            {savedAt && <span className="sk-hint">{t(bookMode ? "books.saved_at" : "lib.saved_at", { time: new Date(savedAt).toLocaleTimeString() })}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

/** 按设置存进角色库；返回存好以后它在角色库里的样子（之后接着更新它），不存时是 null。 */
export async function saveToLibrary(backend: FormBackend, sheets: unknown, origin: Origin | null, v: LibrarySave): Promise<Origin | null> {
  if (v.mode === "none") return null;
  const body = { sheets: sheets as never, name: v.name, summary: v.summary, author: v.author };
  if (v.author) rememberAuthor(v.author);
  if (v.mode === "update" && origin) {
    const password = origin.password ?? (v.current || null);
    const saved = await backend.updateCharacter(origin.id, { ...body, password, new_password: v.newPassword ? v.newPassword : null });
    return { id: saved.id, name: saved.name, summary: saved.summary ?? "", password: v.newPassword || password, locked: saved.locked ?? false, own: origin.own };
  }
  const saved = await backend.createCharacter({ ...body, password: v.password || null });
  return { id: saved.id, name: saved.name, summary: saved.summary ?? "", password: v.password || null, locked: saved.locked ?? false, own: true };
}
