import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox } from "../ui/components";
import { translateCode } from "../ui/errors";
import { Markdown } from "../ui/markdown";
import { useFormBackend } from "./formBackend";

type Proposal = Schemas["CopilotProposal"];
/** 一轮问答；助手的回答带着可以一键应用的修改（applied 记着哪几处已经应用了）。 */
export type CopilotTurn = { role: "user" | "assistant"; text: string; proposals?: Proposal[]; applied?: number[] };
/** 打开助手时正在看的地方：第几张卡（标签）、哪个分组的第几条（编辑条目时）。 */
export type CopilotFocus = { sheet: number; group?: string; index?: number };

/** 建卡页里任何地方都能打开助手（例如编辑条目的侧栏）。 */
export const CopilotContext = createContext<((focus?: CopilotFocus) => void) | null>(null);
/** 工作台在第几张卡上（打开助手时带上）。 */
export const SheetIndexContext = createContext(0);

export function useCopilot(): ((focus?: CopilotFocus) => void) | null {
  return useContext(CopilotContext);
}

/** “问助手”按钮：放在编辑条目的侧栏里。 */
export function CopilotButton({ group, index }: { group?: string; index?: number }) {
  const { t } = useI18n();
  const open = useCopilot();
  const sheet = useContext(SheetIndexContext);
  if (!open) return null;
  return (
    <button type="button" className="cp-button" onClick={() => open({ sheet, group, index })}>
      ✦ {t("cp.button")}
    </button>
  );
}

/** 助手的对话面板：问题、回答（Markdown）、可以一键应用的修改（引擎检查出的问题也列出来）。 */
export function CopilotPanel({
  turns,
  setTurns,
  focus,
  focusLabel,
  question,
  onApply,
  title,
  onClose,
}: {
  turns: CopilotTurn[];
  setTurns: (f: (t: CopilotTurn[]) => CopilotTurn[]) => void;
  focus: CopilotFocus | null;
  focusLabel: string;
  /** 问的时候带上的上下文：整套卡、正在看的地方 */
  question: (text: string) => Schemas["CopilotQuestion"];
  onApply: (p: Proposal) => void;
  /** 这处修改的标题（例如“把正在编辑的这一条换成 XX”） */
  title: (p: Proposal) => string;
  onClose: () => void;
}) {
  const { t, lang } = useI18n();
  const backend = useFormBackend();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [turns.length, busy]);
  const ask = async () => {
    const q = text.trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    const body = question(q);
    setTurns((ts) => [...ts, { role: "user", text: q }]);
    setText("");
    try {
      const a = await backend.copilot(body);
      setTurns((ts) => [...ts, { role: "assistant", text: a.answer, proposals: [...(a.proposals ?? [])], applied: [] }]);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const apply = (turn: number, i: number, p: Proposal) => {
    onApply(p);
    setTurns((ts) => ts.map((x, j) => (j === turn ? { ...x, applied: [...(x.applied ?? []), i] } : x)));
  };
  return (
    <aside className="sk-drawer cp-panel" aria-label={t("cp.title")}>
      <div className="sk-drawer-head">
        <h3>✦ {t("cp.title")}</h3>
        <span className="sk-row">
          {turns.length > 0 && (
            <button type="button" className="sk-link" onClick={() => setTurns(() => [])}>
              {t("cp.clear")}
            </button>
          )}
          <button type="button" className="sk-link" onClick={onClose}>
            {t("play.close")}
          </button>
        </span>
      </div>
      <p className="sk-hint cp-focus">{t(focus?.group !== undefined && focus.index !== undefined ? "cp.focus_entry" : "cp.focus_sheet", { where: focusLabel })}</p>
      {turns.length === 0 && (
        <div className="sk-hint cp-intro">
          <p>{t("cp.intro")}</p>
          <ul>
            <li>{t("cp.example1")}</li>
            <li>{t("cp.example2")}</li>
            <li>{t("cp.example3")}</li>
          </ul>
        </div>
      )}
      <div className="cp-turns">
        {turns.map((turn, k) =>
          turn.role === "user" ? (
            <div key={k} className="cp-q">
              {turn.text}
            </div>
          ) : (
            <div key={k} className="cp-a">
              <Markdown text={turn.text} />
              {(turn.proposals ?? []).map((p, i) => (
                <div key={i} className="cp-prop">
                  <div className="cp-prop-head">
                    <strong>{title(p)}</strong>
                    {(turn.applied ?? []).includes(i) ? (
                      <span className="cf-ok">✓ {t("cp.applied")}</span>
                    ) : (
                      <button type="button" className="sk-primary" onClick={() => apply(k, i, p)}>
                        {t("cp.apply")}
                      </button>
                    )}
                  </div>
                  {p.note && <p className="sk-hint">{p.note}</p>}
                  <details>
                    <summary>{t("cp.show_change")}</summary>
                    <pre className="sk-code">{JSON.stringify(p.kind === "entry" ? p.entry : { name: p.name || undefined, fields: p.fields }, null, 2)}</pre>
                  </details>
                  {(p.problems ?? []).length > 0 && (
                    <div className="cp-problems">
                      <p>{t("cp.problems")}</p>
                      <ul>
                        {(p.problems ?? []).map((x, j) => (
                          <li key={j}>
                            {translateCode(lang, x.code, x.params)}
                            {x.path ? <span className="sk-hint"> ({x.path})</span> : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ),
        )}
        {busy && <p className="sk-hint">{t("cp.thinking")}</p>}
        <ErrorBox error={error} />
        <div ref={end} />
      </div>
      <div className="cp-input">
        <textarea
          rows={3}
          value={text}
          placeholder={t("cp.placeholder")}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void ask();
          }}
        />
        <div className="sk-row">
          <span className="sk-hint">{t("cp.cost_hint")}</span>
          <button type="button" className="sk-primary" disabled={busy || !text.trim()} onClick={() => void ask()}>
            {t("cp.send")}
          </button>
        </div>
      </div>
    </aside>
  );
}

export function entryName(p: Proposal): string {
  const e = p.entry as { name?: unknown } | null | undefined;
  return typeof e?.name === "string" ? e.name : "";
}
