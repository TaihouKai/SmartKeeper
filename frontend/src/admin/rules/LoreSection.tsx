import { useState } from "react";
import { api, call, type Schemas } from "../../api/client";
import { useI18n } from "../../i18n";
import { ErrorBox } from "../../ui/components";
import { useAction } from "../../ui/hooks";
import type { Pack } from "./model";
import { SectionHead } from "./sections";

type Entry = Schemas["LoreEntry"];

const SHOWN = 40; // 一次最多列这么多条（资料库可能有几百条）

const splitKeys = (text: string) =>
  text
    .split(/[,，\n]/)
    .map((x) => x.trim())
    .filter(Boolean);

/** 一条：标题、关键词、开关；点开改关键词和正文。 */
function LoreRow({ entry, onChange, onRemove }: { entry: Entry; onChange: (e: Entry) => void; onRemove: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <div className="wb-panel">
      <div className="sk-row">
        <label className="sk-inline">
          <input type="checkbox" checked={!entry.disabled} onChange={(e) => onChange({ ...entry, disabled: !e.target.checked })} /> {entry.title}
        </label>
        <span className="sk-hint">{entry.keys.join("、")}</span>
        <button className="sk-link" onClick={() => setOpen(!open)}>
          {open ? t("common.hide") : t("rules.lore.edit")}
        </button>
        <button className="sk-link" onClick={onRemove}>
          {t("common.remove")}
        </button>
      </div>
      {open && (
        <>
          <label>
            {t("rules.lore.title")}
            <input value={entry.title} onChange={(e) => onChange({ ...entry, title: e.target.value })} />
          </label>
          <label title={t("rules.lore.keys_hint")}>
            {t("rules.lore.keys")}
            <input value={entry.keys.join(", ")} onChange={(e) => onChange({ ...entry, keys: splitKeys(e.target.value) })} />
          </label>
          <label>
            {t("rules.lore.content")}
            <textarea rows={6} value={entry.content} onChange={(e) => onChange({ ...entry, content: e.target.value })} />
          </label>
        </>
      )}
    </div>
  );
}

/** 资料库：背景设定，引擎按关键词挑进 KP 的上下文。能搜、开关、改；能从世界书（World Info JSON）导入。 */
export function LoreSection({ pack, onChange }: { pack: Pack; onChange: (p: Pack) => void }) {
  const { t } = useI18n();
  const lore = pack.lore ?? [];
  const [q, setQ] = useState("");
  const act = useAction();
  const set = (list: Entry[]) => onChange({ ...pack, lore: list });
  const query = q.trim().toLowerCase();
  const matches = lore
    .map((e, i) => ({ e, i }))
    .filter(({ e }) => !query || e.title.toLowerCase().includes(query) || e.keys.some((k) => k.toLowerCase().includes(query)));
  const enabled = lore.filter((e) => !e.disabled).length;
  const importFile = (file: File, replace: boolean) =>
    void act.run(async () => {
      const got = await call(api.POST("/api/admin/lore/from-world-info", { body: { text: await file.text() } }));
      set(replace ? got : [...lore, ...got]);
    });
  return (
    <>
      <SectionHead title={t("rules.lore_title")} hint={t("rules.lore_hint")} />
      <p className="sk-hint">{t("rules.lore.count", { n: String(lore.length), on: String(enabled) })}</p>
      <div className="sk-row">
        <input value={q} placeholder={t("rules.lore.search")} onChange={(e) => setQ(e.target.value)} />
        <label className="sk-inline">
          {t("rules.lore.import_add")}
          <input type="file" accept=".json" onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0], false)} />
        </label>
        <label className="sk-inline">
          {t("rules.lore.import_replace")}
          <input type="file" accept=".json" onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0], true)} />
        </label>
        <button onClick={() => set([...lore, { title: t("rules.lore.new_title"), keys: [], content: "", secondary: [], logic: "any", case_sensitive: false, order: 100, disabled: false }])}>
          {t("rules.lore.add")}
        </button>
      </div>
      <ErrorBox error={act.error} />
      {matches.slice(0, SHOWN).map(({ e, i }) => (
        <LoreRow key={i} entry={e} onChange={(x) => set(lore.map((y, j) => (j === i ? x : y)))} onRemove={() => set(lore.filter((_, j) => j !== i))} />
      ))}
      {matches.length > SHOWN && <p className="sk-hint">{t("rules.lore.more", { n: String(matches.length - SHOWN) })}</p>}
      {lore.length === 0 && <p className="sk-hint">{t("rules.lore.empty")}</p>}
    </>
  );
}
