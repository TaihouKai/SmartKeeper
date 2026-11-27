import { useState } from "react";
import { api, call, type Schemas } from "../api/client";
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

type Price = { input: number; cached: number; output: number };
type Call = Schemas["LLMCallRecord"];

/** 一次调用的花费（美元）：模型名按最长的前缀找价格；没配价格的是 null。 */
export function callCost(c: Pick<Call, "model" | "input_tokens" | "cached_input_tokens" | "output_tokens">, prices: Record<string, Price>): number | null {
  const key = Object.keys(prices)
    .filter((k) => c.model.startsWith(k))
    .sort((a, b) => b.length - a.length)[0];
  if (key === undefined) return null;
  const p = prices[key];
  if (!p) return null;
  const fresh = Math.max(0, c.input_tokens - c.cached_input_tokens);
  return (fresh * p.input + c.cached_input_tokens * p.cached + c.output_tokens * p.output) / 1e6;
}

const usd = (x: number | null) => (x === null ? "—" : `$${x.toFixed(4)}`);

/** “LLM 调用”面板：按用途汇总（次数、输入、命中缓存、输出、花费），每次调用的 prompt、响应、搜索记录、token、耗时。 */
export function LlmPanel({ gameId }: { gameId: string }) {
  const { t } = useI18n();
  const calls = usePoll(() => call(api.GET("/api/admin/games/{game_id}/llm-calls", { params: { path: { game_id: gameId }, query: { limit: 300 } } })), 30_000, [gameId]);
  const priceList = usePoll(() => call(api.GET("/api/admin/model-prices")), 600_000);
  const [open, setOpen] = useState<number | null>(null);
  const list = calls.data ?? [];
  const prices = priceList.data ?? {};
  const byPurpose = new Map<string, { n: number; inTok: number; cached: number; outTok: number; cost: number | null }>();
  for (const c of list) {
    const row = byPurpose.get(c.purpose) ?? { n: 0, inTok: 0, cached: 0, outTok: 0, cost: 0 };
    const cost = callCost(c, prices);
    byPurpose.set(c.purpose, {
      n: row.n + 1,
      inTok: row.inTok + c.input_tokens,
      cached: row.cached + c.cached_input_tokens,
      outTok: row.outTok + c.output_tokens,
      cost: row.cost === null || cost === null ? null : row.cost + cost,
    });
  }
  const rows = [...byPurpose.entries()].sort((a, b) => b[1].inTok - a[1].inTok);
  const total = rows.reduce<number | null>((s, [, r]) => (s === null || r.cost === null ? null : s + r.cost), 0);
  return (
    <Section title={t("admin.panel.llm")}>
      <table className="sk-table">
        <thead>
          <tr>
            <th>{t("llm.purpose")}</th>
            <th>{t("llm.calls")}</th>
            <th>{t("llm.input")}</th>
            <th>{t("llm.cached")}</th>
            <th>{t("llm.output")}</th>
            <th>{t("llm.cost")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([purpose, r]) => (
            <tr key={purpose}>
              <td>{purpose}</td>
              <td>{r.n}</td>
              <td>{r.inTok}</td>
              <td>{r.cached}</td>
              <td>{r.outTok}</td>
              <td>{usd(r.cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="sk-hint">{t("llm.totals", { n: String(list.length), cost: usd(total) })}</p>
      <table className="sk-table">
        <tbody>
          {list.map((c) => (
            <tr key={c.id} onClick={() => setOpen(open === c.id ? null : c.id)} className={c.valid === false || c.error ? "sk-warn" : ""}>
              <td>#{c.id}</td>
              <td>{c.purpose}</td>
              <td>{c.model}</td>
              <td>{c.input_tokens}/{c.cached_input_tokens}/{c.output_tokens}</td>
              <td>{usd(callCost(c, prices))}</td>
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
