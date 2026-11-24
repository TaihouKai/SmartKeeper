import { acceptCompletion, autocompletion, closeBrackets, closeBracketsKeymap, completionKeymap, startCompletion, type CompletionContext, type CompletionResult } from "@codemirror/autocomplete";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { python } from "@codemirror/lang-python";
import { HighlightStyle, bracketMatching, indentOnInput, indentUnit, syntaxHighlighting } from "@codemirror/language";
import { forceLinting, linter, lintGutter, type Diagnostic } from "@codemirror/lint";
import { EditorState, type Extension } from "@codemirror/state";
import { EditorView, drawSelection, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers, placeholder as cmPlaceholder } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { useI18n } from "../i18n";
import { suggest } from "./complete";
import { translateCode } from "./errors";

export type CodeProblem = { code: string; params?: Record<string, unknown> | null };
export type CodeCheck = (text: string) => Promise<{ problems: CodeProblem[]; names: string[] }>;
export type CodeEditorHandle = {
  /** 在光标处插入（替换选中的文字），插完把光标放到插入内容后面。 */
  insert: (text: string) => void;
  focus: () => void;
  /** 光标前的名字（可以带点），查找引用用。 */
  wordAtCursor: () => string;
};

const WORD = /[\p{L}_][\p{L}\p{N}_.]*$/u;

const highlight = HighlightStyle.define([
  { tag: tags.keyword, color: "var(--cm-keyword)", fontWeight: "600" },
  { tag: [tags.string], color: "var(--cm-string)" },
  { tag: [tags.number, tags.bool], color: "var(--cm-number)" },
  { tag: tags.comment, color: "var(--cm-comment)" },
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName)], color: "var(--cm-call)" },
  { tag: [tags.propertyName], color: "var(--cm-prop)" },
  { tag: [tags.operator, tags.compareOperator, tags.arithmeticOperator], color: "var(--cm-op)" },
]);

const theme = EditorView.theme({
  "&": { backgroundColor: "var(--card)", color: "var(--fg)", fontSize: "13px", height: "100%" },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": { fontFamily: "ui-monospace, 'Cascadia Code', Consolas, monospace", lineHeight: "1.6" },
  ".cm-content": { caretColor: "var(--accent)", padding: "6px 0" },
  // drawSelection 自己画光标，不用 caretColor；默认是黑的，深色模式下看不见
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--fg)", borderLeftWidth: "2px" },
  ".cm-gutters": { backgroundColor: "var(--wb-sunken)", color: "var(--muted)", border: "none", borderRight: "1px solid var(--line)" },
  ".cm-activeLine": { backgroundColor: "color-mix(in srgb, var(--accent) 6%, transparent)" },
  ".cm-activeLineGutter": { backgroundColor: "color-mix(in srgb, var(--accent) 12%, transparent)", color: "var(--fg)" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground, ::selection": { backgroundColor: "color-mix(in srgb, var(--accent) 28%, transparent) !important" },
  ".cm-placeholder": { color: "var(--muted)", opacity: "0.7" },
  ".cm-tooltip": { backgroundColor: "var(--card)", border: "1px solid var(--line)", borderRadius: "6px", boxShadow: "0 6px 20px rgba(0,0,0,.18)" },
  ".cm-tooltip-autocomplete > ul > li": { padding: "2px 10px" },
  ".cm-tooltip-autocomplete > ul > li[aria-selected]": { backgroundColor: "color-mix(in srgb, var(--accent) 25%, var(--card))", color: "var(--fg)" },
  ".cm-completionDetail": { color: "var(--muted)", fontStyle: "normal", marginLeft: "6px" },
  ".cm-diagnostic-error": { borderLeft: "3px solid var(--warn)" },
  ".cm-lintRange-error": { backgroundImage: "none", textDecoration: "underline wavy var(--warn)", textUnderlineOffset: "3px" },
  ".cm-matchingBracket": { backgroundColor: "color-mix(in srgb, var(--ok) 25%, transparent)", outline: "none" },
});

/**
 * 写公式和技能脚本的编辑器（CodeMirror）：行号、Python 高亮、括号配对、自动缩进、
 * 出错的行标波浪线（check 返回的问题带 line 时标那一行），补全用 check 返回的名字一段一段列。
 */
export const CodeEditor = forwardRef<
  CodeEditorHandle,
  {
    value: string;
    onChange: (v: string) => void;
    check: CodeCheck;
    placeholder?: string;
    /** 编辑器至少多高（行）；放在固定高度的容器里时不用给 */
    minLines?: number;
    /** 每次校验完把问题（已翻译、带行号）交出去 */
    onProblems?: (messages: string[]) => void;
    className?: string;
  }
>(function CodeEditor({ value, onChange, check, placeholder, minLines, onProblems, className }, ref) {
  const { t, lang } = useI18n();
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  // 回调和数据放在 ref 里：编辑器只建一次，扩展里读最新的
  const latest = useRef({ onChange, check, onProblems, lang, t });
  latest.current = { onChange, check, onProblems, lang, t };
  const names = useRef<string[]>([]);

  useEffect(() => {
    if (!host.current) return;
    const lint = linter(
      async (v) => {
        const text = v.state.doc.toString();
        let r: Awaited<ReturnType<CodeCheck>>;
        try {
          r = await latest.current.check(text);
        } catch {
          return [];
        }
        names.current = r.names;
        if (!text.trim()) {
          latest.current.onProblems?.([]);
          return [];
        }
        const { lang: l, t: tr } = latest.current;
        const out: Diagnostic[] = [];
        const messages: string[] = [];
        for (const p of r.problems) {
          const msg = translateCode(l, p.code, p.params ?? undefined);
          const line = p.params?.line;
          const doc = v.state.doc;
          if (typeof line === "number" && line >= 1 && line <= doc.lines) {
            const ln = doc.line(line);
            const from = ln.from + (ln.text.length - ln.text.trimStart().length);
            out.push({ from, to: Math.max(from + 1, ln.to), severity: "error", message: msg });
            messages.push(`${tr("script.line", { n: String(line) })}: ${msg}`);
          } else {
            out.push({ from: 0, to: Math.max(1, Math.min(doc.length, doc.line(1).to)), severity: "error", message: msg });
            messages.push(msg);
          }
        }
        latest.current.onProblems?.(messages);
        return out;
      },
      { delay: 400 },
    );
    const complete = (ctx: CompletionContext): CompletionResult | null => {
      const before = ctx.state.sliceDoc(Math.max(0, ctx.pos - 120), ctx.pos);
      const word = WORD.exec(before)?.[0] ?? "";
      if (!word && !ctx.explicit) return null;
      const items = suggest(names.current, word);
      if (!items.length) return null;
      return {
        from: ctx.pos - word.length,
        filter: false,
        options: items.map((s, i) => ({ label: s.label, apply: s.insert, detail: s.more ? "." : undefined, boost: -i, type: s.more ? "namespace" : "variable" })),
      };
    };
    const exts: Extension[] = [
      lineNumbers(),
      highlightActiveLineGutter(),
      highlightActiveLine(),
      drawSelection(),
      history(),
      indentUnit.of("    "),
      EditorState.tabSize.of(4),
      python(),
      syntaxHighlighting(highlight),
      indentOnInput(),
      bracketMatching(),
      closeBrackets(),
      autocompletion({ override: [complete], icons: false }),
      lint,
      lintGutter(),
      keymap.of([{ key: "Tab", run: acceptCompletion }, ...closeBracketsKeymap, ...completionKeymap, ...historyKeymap, indentWithTab, ...defaultKeymap]),
      theme,
      EditorView.lineWrapping,
      EditorView.updateListener.of((u) => {
        if (u.docChanged) latest.current.onChange(u.state.doc.toString());
        // 打完一个点就把下一段列出来
        if (u.docChanged && u.transactions.some((tr) => tr.isUserEvent("input.type"))) {
          const pos = u.state.selection.main.head;
          if (u.state.sliceDoc(pos - 1, pos) === ".") startCompletion(u.view);
        }
      }),
    ];
    if (placeholder) exts.push(cmPlaceholder(placeholder));
    if (minLines) exts.push(EditorView.theme({ ".cm-content, .cm-gutter": { minHeight: `${minLines * 1.6 + 0.8}em` } }));
    view.current = new EditorView({ parent: host.current, state: EditorState.create({ doc: value, extensions: exts }) });
    return () => {
      view.current?.destroy();
      view.current = null;
    };
    // 编辑器只建一次；value 的变化由下面的 effect 同步
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 外面改了内容（撤销、换了文档、表格里改了同一格）时同步进来
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    const cur = v.state.doc.toString();
    if (cur !== value) {
      const head = Math.min(v.state.selection.main.head, value.length);
      v.dispatch({ changes: { from: 0, to: cur.length, insert: value }, selection: { anchor: head } });
    }
  }, [value]);

  // check 换了（例如规则包改了，名字变了）就重新校验
  useEffect(() => {
    if (view.current) forceLinting(view.current);
  }, [check]);

  useImperativeHandle(ref, () => ({
    insert: (text: string) => {
      const v = view.current;
      if (!v) return;
      const { from, to } = v.state.selection.main;
      v.dispatch({ changes: { from, to, insert: text }, selection: { anchor: from + text.length }, scrollIntoView: true });
      v.focus();
    },
    focus: () => view.current?.focus(),
    wordAtCursor: () => {
      const v = view.current;
      if (!v) return "";
      const pos = v.state.selection.main.head;
      const line = v.state.doc.lineAt(pos);
      const before = WORD.exec(line.text.slice(0, pos - line.from))?.[0] ?? "";
      const after = /^[\p{L}\p{N}_.]*/u.exec(line.text.slice(pos - line.from))?.[0] ?? "";
      return (before + after).replace(/\.$/, "");
    },
  }));

  return <div ref={host} className={className ? `sk-code-editor ${className}` : "sk-code-editor"} />;
});
