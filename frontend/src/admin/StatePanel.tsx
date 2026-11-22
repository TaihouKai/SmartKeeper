import { useState } from "react";
import { api, call } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, Section } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";

/** “世界状态”面板：当前状态和各轮快照，手动提交 patch（落成 admin_override 和 state_patch 事件）。 */
export function StatePanel({ gameId }: { gameId: string }) {
  const { t } = useI18n();
  const detail = usePoll(() => call(api.GET("/api/admin/games/{game_id}", { params: { path: { game_id: gameId } } })), 60_000, [gameId]);
  const [round, setRound] = useState<number | null>(null);
  const state = usePoll(
    () => call(api.GET("/api/admin/games/{game_id}/state", { params: { path: { game_id: gameId }, query: round === null ? {} : { round } } })),
    30_000,
    [gameId, round],
  );
  const [ops, setOps] = useState('[\n  {"op": "replace", "path": "/kp_notes", "value": ""}\n]');
  const [note, setNote] = useState("");
  const act = useAction();
  const rounds = detail.data?.game.current_round ?? 0;
  return (
    <Section title={t("admin.panel.state")}>
      <select value={round === null ? "" : String(round)} onChange={(e) => setRound(e.target.value === "" ? null : Number(e.target.value))}>
        <option value="">{t("state.current")}</option>
        {Array.from({ length: rounds }, (_, i) => i + 1).map((n) => (
          <option key={n} value={n}>{t("state.snapshot", { round: String(n) })}</option>
        ))}
      </select>
      <ErrorBox error={state.error} />
      <pre className="sk-code sk-card">{state.data ? JSON.stringify(state.data, null, 1) : ""}</pre>
      <h3>{t("state.patch")}</h3>
      <p className="sk-hint">{t("state.patch_hint")}</p>
      <textarea rows={8} className="sk-code" value={ops} onChange={(e) => setOps(e.target.value)} />
      <label>{t("state.note")}<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
      <button
        className="sk-primary"
        disabled={act.busy}
        onClick={() =>
          void act.run(async () => {
            await call(api.PATCH("/api/admin/games/{game_id}/state", { params: { path: { game_id: gameId } }, body: { ops: JSON.parse(ops), note } }));
            void state.refresh();
          })
        }
      >
        {t("state.apply")}
      </button>
      <ErrorBox error={act.error} />
    </Section>
  );
}

/** “LLM 调用”面板：每次调用的 prompt、响应、搜索记录、token、耗时。 */
export function LlmPanel({ gameId }: { gameId: string }) {
  const { t } = useI18n();
  const calls = usePoll(() => call(api.GET("/api/admin/games/{game_id}/llm-calls", { params: { path: { game_id: gameId }, query: { limit: 300 } } })), 30_000, [gameId]);
  const [open, setOpen] = useState<number | null>(null);
  const list = calls.data ?? [];
  const tokensIn = list.reduce((s, c) => s + c.input_tokens, 0);
  const tokensOut = list.reduce((s, c) => s + c.output_tokens, 0);
  return (
    <Section title={t("admin.panel.llm")}>
      <p className="sk-hint">{t("llm.totals", { n: String(list.length), in: String(tokensIn), out: String(tokensOut) })}</p>
      <table className="sk-table">
        <tbody>
          {list.map((c) => (
            <tr key={c.id} onClick={() => setOpen(open === c.id ? null : c.id)} className={c.valid === false || c.error ? "sk-warn" : ""}>
              <td>#{c.id}</td>
              <td>{c.purpose}</td>
              <td>{c.model}</td>
              <td>{c.input_tokens}/{c.output_tokens}</td>
              <td>{c.duration_ms} ms</td>
              <td>{c.valid === null ? "" : c.valid ? "✓" : "✗"} {c.searches.length ? `🔍${c.searches.length}` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {list.filter((c) => c.id === open).map((c) => (
        <div key={c.id} className="sk-card">
          {c.error && <pre className="sk-error">{c.error}</pre>}
          {c.searches.length > 0 && (
            <>
              <h4>{t("llm.searches")}</h4>
              <ul>{c.searches.map((s, i) => <li key={i}>{s.query} — {s.urls.join(", ")}</li>)}</ul>
            </>
          )}
          <h4>{t("llm.system")}</h4>
          <pre className="sk-code">{c.system}</pre>
          <h4>{t("llm.messages")}</h4>
          <pre className="sk-code">{c.messages.map((m) => `[${String(m.role)}]\n${typeof m.content === "string" ? m.content : JSON.stringify(m.content)}`).join("\n\n")}</pre>
          <h4>{t("llm.response")}</h4>
          <pre className="sk-code">{c.response}</pre>
        </div>
      ))}
    </Section>
  );
}
