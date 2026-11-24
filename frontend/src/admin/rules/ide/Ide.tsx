import { useCallback, useMemo, useRef, useState } from "react";
import { useI18n } from "../../../i18n";
import { CodeEditor, type CodeEditorHandle } from "../../../ui/CodeEditor";
import { FormulaHelpBody } from "../../../ui/FormulaHelp";
import type { Validate } from "../../fieldCard";
import { describePath, docFor, getAt, setAt, shortTitle, type Pack } from "../model";
import { NamesPanel, SearchPanel, TryPanel } from "./panels";

type Tool = "names" | "try" | "search" | "help";

/**
 * 规则编辑器右边的 IDE：上面是打开的公式和脚本（标签页），下面是工具（名字、试运行、查找、速查）。
 * 文档就是规则包里的一个路径；改动直接写回规则包，和左边表格里看到的是同一份。
 */
export function Ide({
  pack,
  setPack,
  validate,
  docs,
  active,
  onActivate,
  onClose,
  onOpen,
  onReveal,
  onGoSamples,
}: {
  pack: Pack;
  setPack: (f: (p: Pack) => Pack) => void;
  validate: Validate;
  docs: string[];
  active: string | null;
  onActivate: (path: string) => void;
  onClose: (path: string) => void;
  onOpen: (path: string) => void;
  /** 在左边显示这一段所在的位置 */
  onReveal: (path: string) => void;
  onGoSamples: () => void;
}) {
  const { t } = useI18n();
  const editor = useRef<CodeEditorHandle>(null);
  const [tool, setTool] = useState<Tool>("names");
  const [query, setQuery] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [split, setSplit] = useState(58); // 编辑器占上面百分之几
  const body = useRef<HTMLDivElement>(null);
  const doc = active ? docFor(pack, active) : null;
  const value = active ? getAt(pack, active) : undefined;
  const text = typeof value === "string" ? value : "";
  const check = useCallback(
    (f: string) => (doc ? validate(f, doc.template, doc.inEntry, doc.scope) : Promise.resolve({ problems: [], names: [] })),
    // doc 每次都是新对象，按它的内容决定要不要换
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [validate, doc?.template, doc?.inEntry, doc?.scope],
  );
  const titles = useMemo(() => Object.fromEntries(docs.map((p) => [p, describePath(t, pack, p)])), [docs, pack, t]);

  const drag = (e: React.PointerEvent) => {
    const box = body.current?.getBoundingClientRect();
    if (!box) return;
    e.preventDefault();
    const move = (ev: PointerEvent) => setSplit(Math.min(85, Math.max(20, ((ev.clientY - box.top) / box.height) * 100)));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div className="wb-ide">
      <div className="wb-ide-tabs" role="tablist">
        {docs.map((p) => {
          const parts = titles[p] ?? [];
          return (
            <div key={p} className={p === active ? "wb-ide-tab active" : "wb-ide-tab"} role="tab" aria-selected={p === active} title={parts.join(" › ")}>
              <button type="button" className="wb-ide-tab-name" onClick={() => onActivate(p)}>
                <span className={docFor(pack, p)?.kind === "script" ? "wb-kind wb-kind-script" : "wb-kind"}>{docFor(pack, p)?.kind === "script" ? "py" : "ƒ"}</span>
                {shortTitle(t, pack, p)}
              </button>
              <button type="button" className="wb-ide-tab-x" aria-label={t("ide.close_tab")} onClick={() => onClose(p)}>
                ×
              </button>
            </div>
          );
        })}
      </div>
      <div className="wb-ide-body" ref={body}>
        <div className="wb-ide-editor" style={{ flexBasis: `${split}%` }}>
          {active && doc ? (
            <>
              <div className="wb-ide-crumbs">
                <button type="button" className="sk-link" onClick={() => onReveal(active)} title={t("ide.reveal")}>
                  {(titles[active] ?? []).join(" › ")}
                </button>
                <span className={problems.length ? "wb-status bad" : "wb-status ok"}>{problems.length ? t("ide.n_problems", { n: String(problems.length) }) : t("ide.ok")}</span>
              </div>
              <CodeEditor
                key={active}
                ref={editor}
                className="wb-cm"
                value={text}
                check={check}
                placeholder={doc.kind === "script" ? t("script.ph") : t("rules.ph.formula")}
                onChange={(v) => setPack((p) => setAt(p, active, v))}
                onProblems={setProblems}
              />
              {problems.length > 0 && (
                <ul className="wb-ide-problems">
                  {problems.map((m, i) => (
                    <li key={i}>{m}</li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <div className="wb-ide-empty">
              <h4>{t("ide.empty_title")}</h4>
              <p>{t("ide.empty_hint")}</p>
            </div>
          )}
        </div>
        <div className="wb-ide-split" role="separator" aria-orientation="horizontal" onPointerDown={drag} />
        <div className="wb-ide-tools">
          <div className="wb-ide-tooltabs" role="tablist">
            {(["names", "try", "search", "help"] as Tool[]).map((k) => (
              <button key={k} type="button" role="tab" aria-selected={tool === k} className={tool === k ? "active" : ""} onClick={() => setTool(k)}>
                {t(`ide.tool.${k}`)}
              </button>
            ))}
          </div>
          <div className="wb-ide-toolbody">
            {tool === "names" && <NamesPanel pack={pack} doc={doc} insert={(s) => editor.current?.insert(s)} />}
            {tool === "try" && <TryPanel key={active ?? ""} pack={pack} doc={doc} onGoSamples={onGoSamples} />}
            {tool === "search" && <SearchPanel pack={pack} query={query} setQuery={setQuery} onOpen={onOpen} fromCursor={() => editor.current?.wordAtCursor() ?? ""} />}
            {tool === "help" && <FormulaHelpBody />}
          </div>
        </div>
      </div>
    </div>
  );
}
