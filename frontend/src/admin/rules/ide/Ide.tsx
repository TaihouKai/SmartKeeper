import { useCallback, useMemo, useRef, useState } from "react";
import { useI18n } from "../../../i18n";
import { CodeEditor, type CodeEditorHandle } from "../../../ui/CodeEditor";
import { FormulaHelpBody } from "../../../ui/FormulaHelp";
import type { Validate } from "../../fieldCard";
import { describeName, describePath, docFor, getAt, setAt, shortTitle, type Pack } from "../model";
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
  const configEditor = useRef<CodeEditorHandle>(null);
  // 插入名字、查光标处的名字时用最后一个获得焦点的编辑器
  const [focused, setFocused] = useState<"config" | "main">("main");
  const current = () => (focused === "config" ? configEditor.current : editor.current);
  const [tool, setTool] = useState<Tool>("names");
  const [query, setQuery] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [configProblems, setConfigProblems] = useState<string[]>([]);
  const [split, setSplit] = useState(58); // 编辑器占上面百分之几
  const body = useRef<HTMLDivElement>(null);
  const doc = active ? docFor(pack, active) : null;
  const entry = doc?.kind === "entry";
  // 条目：下面的编辑器是技能脚本，上面是技能设置；其余文档只有一个编辑器
  const mainPath = active && entry ? `${active}.script` : active;
  const value = mainPath ? getAt(pack, mainPath) : undefined;
  const text = typeof value === "string" ? value : "";
  const configText = active && entry ? String(getAt(pack, `${active}.config`) ?? "") : "";
  const scope = entry ? "script" : doc?.scope;
  const check = useCallback(
    (f: string) => (doc ? validate(f, doc.template, doc.inEntry, scope, entry ? configText : undefined) : Promise.resolve({ problems: [], names: [] })),
    // doc 每次都是新对象，按它的内容决定要不要换；条目的设置和脚本可以互相引用名字，另一半变了也要重新校验
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [validate, doc?.template, doc?.inEntry, scope, entry ? configText : ""],
  );
  const checkConfig = useCallback(
    (f: string) => (doc ? validate(f, doc.template, doc.inEntry, "config", text) : Promise.resolve({ problems: [], names: [] })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [validate, doc?.template, doc?.inEntry, text],
  );
  const allProblems = entry ? [...configProblems, ...problems] : problems;
  // 悬停提示：字段、推导值、本条目的设置和变量的说明
  const describe = (w: string) => describeName(t, pack, doc, w, { config: configText, script: entry ? text : "" });
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
                <span className={docFor(pack, p)?.kind === "entry" ? "wb-kind wb-kind-script" : "wb-kind"}>{docFor(pack, p)?.kind === "entry" ? "py" : "ƒ"}</span>
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
                <span className={allProblems.length ? "wb-status bad" : "wb-status ok"}>{allProblems.length ? t("ide.n_problems", { n: String(allProblems.length) }) : t("ide.ok")}</span>
              </div>
              {entry && (
                <div className="wb-part wb-part-config" onFocus={() => setFocused("config")}>
                  <div className="wb-part-head">{t("ide.part.config")}</div>
                  <CodeEditor
                    key={`${active}.config`}
                    ref={configEditor}
                    className="wb-cm wb-cm-config"
                    value={configText}
                    check={checkConfig}
                    onChange={(v) => setPack((p) => setAt(p, `${active}.config`, v))}
                    onProblems={setConfigProblems}
                    describe={describe}
                  />
                </div>
              )}
              <div className="wb-part wb-part-main" onFocus={() => setFocused("main")}>
                {entry && <div className="wb-part-head">{t("ide.part.script")}</div>}
                <CodeEditor
                  key={mainPath ?? ""}
                  ref={editor}
                  className="wb-cm"
                  value={text}
                  check={check}
                  placeholder={entry ? t("script.ph") : t("rules.ph.formula")}
                  onChange={(v) => setPack((p) => setAt(p, mainPath!, v))}
                  onProblems={setProblems}
                  describe={describe}
                />
              </div>
              {allProblems.length > 0 && (
                <ul className="wb-ide-problems">
                  {allProblems.map((m, i) => (
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
            {tool === "names" && <NamesPanel pack={pack} doc={doc} part={entry ? focused : "main"} insert={(s) => current()?.insert(s)} />}
            {tool === "try" && <TryPanel key={active ?? ""} pack={pack} doc={doc} onGoSamples={onGoSamples} />}
            {tool === "search" && <SearchPanel pack={pack} query={query} setQuery={setQuery} onOpen={onOpen} fromCursor={() => current()?.wordAtCursor() ?? ""} />}
            {tool === "help" && <FormulaHelpBody />}
          </div>
        </div>
      </div>
    </div>
  );
}
