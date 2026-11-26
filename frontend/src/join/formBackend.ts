import { createContext, useContext } from "react";
import { api, call, type Schemas } from "../api/client";

/** 建卡表单背后的服务器接口：在某一局里建卡（玩家接口）和在规则书下直接编辑角色库（规则书接口）用同一张表单。 */
export type FormBackend = {
  /** 按现在的填写算数值、找问题 */
  preview: (template: string, sheet: unknown) => Promise<Schemas["PreviewOut"]>;
  /** 检查公式、设置、脚本 */
  validate: (body: Schemas["SheetFormulaIn"]) => Promise<Schemas["FormulaOut"]>;
  /** 自动保存的草稿：取回（没有是 null）、存 */
  loadDraft: () => Promise<{ sheets: unknown[] | null; savedAt: string | null }>;
  /** base：这一页基于的草稿保存时间（"" 是打开时还没有）；草稿被别的页面改过时拒绝 */
  saveDraft: (sheets: unknown[], base: string) => Promise<string | null>;
  /** 存进角色库：新建、更新 */
  createCharacter: (body: Schemas["LibrarySaveIn"]) => Promise<Schemas["LibraryCharacter"]>;
  updateCharacter: (id: string, body: Schemas["LibrarySaveIn"]) => Promise<Schemas["LibraryCharacter"]>;
};

/** 在某一局里建卡：草稿存在服务器上（没有草稿但提交过的，从上次提交的内容接着改）。 */
export const gameBackend: FormBackend = {
  preview: (template, sheet) => call(api.POST("/api/character/preview", { body: { template, sheet: sheet as never } })),
  validate: (body) => call(api.POST("/api/formula/validate", { body })),
  loadDraft: async () => {
    const d = await call(api.GET("/api/character/draft"));
    if (Array.isArray(d.sheets) && d.sheets.length > 0) return { sheets: d.sheets as unknown[], savedAt: d.updated_at ?? null };
    const prev = await call(api.GET("/api/character"));
    return { sheets: prev.length > 0 ? prev.map((x) => ({ template: x.template, sheet: x.sheet })) : null, savedAt: null };
  },
  saveDraft: async (sheets, base) => (await call(api.PUT("/api/character/draft", { body: { sheets: sheets as never, base } }))).updated_at ?? null,
  createCharacter: (body) => call(api.POST("/api/library", { body })),
  updateCharacter: (id, body) => call(api.PUT("/api/library/{char_id}", { params: { path: { char_id: id } }, body })),
};

/** 不进局、在规则书下编辑角色库：按规则书的最新版本检查；草稿只存在这个浏览器里（key 区分是哪个角色）。 */
export function bookBackend(bookId: string, draftKey: string, initial: unknown[] | null): FormBackend {
  const key = `sk.bookDraft.${bookId}.${draftKey}`;
  const path = { book_id: bookId };
  return {
    preview: (template, sheet) => call(api.POST("/api/books/{book_id}/preview", { params: { path }, body: { template, sheet: sheet as never } })),
    validate: (body) => call(api.POST("/api/books/{book_id}/formula", { params: { path }, body })),
    loadDraft: () => {
      try {
        const raw = window.localStorage.getItem(key);
        const d = raw ? (JSON.parse(raw) as { sheets: unknown[]; savedAt: string }) : null;
        if (d && Array.isArray(d.sheets) && d.sheets.length > 0) return Promise.resolve(d);
      } catch {
        // 读不到就用角色库里的
      }
      return Promise.resolve({ sheets: initial, savedAt: null });
    },
    saveDraft: (sheets) => {
      const savedAt = new Date().toISOString();
      try {
        window.localStorage.setItem(key, JSON.stringify({ sheets, savedAt }));
      } catch {
        return Promise.resolve(null);
      }
      return Promise.resolve(savedAt);
    },
    createCharacter: (body) => call(api.POST("/api/books/{book_id}/characters", { params: { path }, body })),
    updateCharacter: (id, body) => call(api.PUT("/api/books/{book_id}/characters/{char_id}", { params: { path: { ...path, char_id: id } }, body })),
  };
}

/** 浏览器里有没有这个角色没存进角色库的修改。 */
export function hasBookDraft(bookId: string, draftKey: string): boolean {
  try {
    return window.localStorage.getItem(`sk.bookDraft.${bookId}.${draftKey}`) !== null;
  } catch {
    return false;
  }
}

/** 存进角色库以后，不用再留着浏览器里的草稿。 */
export function dropBookDraft(bookId: string, draftKey: string): void {
  try {
    window.localStorage.removeItem(`sk.bookDraft.${bookId}.${draftKey}`);
  } catch {
    // 删不掉也无妨
  }
}

export const FormBackendContext = createContext<FormBackend>(gameBackend);

export function useFormBackend(): FormBackend {
  return useContext(FormBackendContext);
}
