import { useEffect, useState } from "react";
import { api, call } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, Section } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";

/** “审核”面板：裁定 JSON、骰子和空间查询结果、各玩家反馈草稿；可编辑、单份重写、发布。 */
export function ReviewPanel({ gameId }: { gameId: string }) {
  const { t } = useI18n();
  const rev = usePoll(() => call(api.GET("/api/admin/games/{game_id}/round/review", { params: { path: { game_id: gameId } } })), 15_000, [gameId]);
  const detail = usePoll(() => call(api.GET("/api/admin/games/{game_id}", { params: { path: { game_id: gameId } } })), 60_000, [gameId]);
  const act = useAction();
  const draft = rev.data?.round.draft as { adjudication?: unknown; feedback?: Record<string, string>; broadcast?: string | null; error?: unknown; leaks?: Record<string, string[]> } | null | undefined;
  const [adjText, setAdjText] = useState("");
  const [feedback, setFeedback] = useState<Record<string, string>>({});
  const [broadcast, setBroadcast] = useState("");
  useEffect(() => {
    setAdjText(draft?.adjudication ? JSON.stringify(draft.adjudication, null, 1) : "");
    setFeedback(draft?.feedback ?? {});
    setBroadcast(draft?.broadcast ?? "");
  }, [rev.data?.round.no, rev.data?.round.status, JSON.stringify(draft)]);
  if (!rev.data) return <Section title={t("admin.panel.review")}>{t("common.loading")}</Section>;
  const names = Object.fromEntries((detail.data?.players ?? []).map((p) => [p.id, p.display_name]));
  const inReview = rev.data.round.status === "review";
  const save = () =>
    void act.run(async () => {
      const body: { adjudication?: never; feedback: Record<string, string>; broadcast?: string | null } = { feedback };
      if (adjText.trim()) body.adjudication = JSON.parse(adjText) as never;
      if (broadcast.trim()) body.broadcast = broadcast;
      await call(api.PUT("/api/admin/games/{game_id}/round/review", { params: { path: { game_id: gameId } }, body }));
      void rev.refresh();
    });
  return (
    <Section title={t("admin.panel.review")}>
      <p>{t("status.round", { round: String(rev.data.round.no) })} · {t(`status.phase.${rev.data.round.status}`)}</p>
      {!inReview && <p className="sk-hint">{t("review.not_in_review")}</p>}
      {draft?.error ? <pre className="sk-error">{JSON.stringify(draft.error, null, 1)}</pre> : null}
      <ErrorBox error={act.error} />
      <h3>{t("review.adjudication")}</h3>
      <textarea rows={16} className="sk-code" value={adjText} onChange={(e) => setAdjText(e.target.value)} disabled={!inReview} />
      <h3>{t("review.feedback")}</h3>
      {Object.keys({ ...feedback, ...Object.fromEntries((detail.data?.players ?? []).filter((p) => p.active).map((p) => [p.id, ""])) }).map((pid) => (
        <div key={pid} className="sk-card">
          <strong>{names[pid] ?? pid}</strong>
          {(draft?.leaks?.[pid] ?? []).length > 0 && (
            <div className="sk-warn">
              {t("review.leaks")}
              <ul>{(draft?.leaks?.[pid] ?? []).map((l, i) => <li key={i}>{l}</li>)}</ul>
            </div>
          )}
          <textarea rows={4} value={feedback[pid] ?? ""} disabled={!inReview} onChange={(e) => setFeedback({ ...feedback, [pid]: e.target.value })} />
          <button disabled={!inReview} onClick={() => void act.run(async () => { await call(api.POST("/api/admin/games/{game_id}/round/rewrite", { params: { path: { game_id: gameId } }, body: { player_id: pid } })); void rev.refresh(); })}>
            {t("review.rewrite")}
          </button>
        </div>
      ))}
      <h3>{t("review.broadcast")}</h3>
      <textarea rows={3} value={broadcast} disabled={!inReview} onChange={(e) => setBroadcast(e.target.value)} />
      <div className="sk-row">
        <button disabled={!inReview || act.busy} onClick={save}>{t("common.save")}</button>
        <button className="sk-primary" disabled={!inReview || act.busy} onClick={() => void act.run(async () => { await call(api.POST("/api/admin/games/{game_id}/round/publish", { params: { path: { game_id: gameId } } })); void rev.refresh(); })}>
          {t("review.publish")}
        </button>
      </div>
      <details>
        <summary>{t("review.declarations")}</summary>
        <pre className="sk-code">{JSON.stringify(rev.data.declarations, null, 1)}</pre>
      </details>
      <details>
        <summary>{t("review.dice")} ({rev.data.dice.length})</summary>
        <pre className="sk-code">{JSON.stringify(rev.data.dice, null, 1)}</pre>
      </details>
      <details>
        <summary>{t("review.queries")} ({rev.data.queries.length})</summary>
        <pre className="sk-code">{JSON.stringify(rev.data.queries, null, 1)}</pre>
      </details>
      <details>
        <summary>{t("review.claims")} ({rev.data.claims.length})</summary>
        <pre className="sk-code">{JSON.stringify(rev.data.claims, null, 1)}</pre>
      </details>
    </Section>
  );
}

/** “日志”面板：全部事件（含 kp_only），可以切换“以某玩家视角查看”来检查隔离。不含玩家间的闲聊。 */
export function LogPanel({ gameId }: { gameId: string }) {
  const { t } = useI18n();
  const detail = usePoll(() => call(api.GET("/api/admin/games/{game_id}", { params: { path: { game_id: gameId } } })), 60_000, [gameId]);
  const [as, setAs] = useState("");
  const events = usePoll(
    () => call(api.GET("/api/admin/games/{game_id}/events", { params: { path: { game_id: gameId }, query: as ? { as } : {} } })),
    15_000,
    [gameId, as],
  );
  return (
    <Section title={t("admin.panel.log")}>
      <select value={as} onChange={(e) => setAs(e.target.value)}>
        <option value="">{t("log.all")}</option>
        <option value="public">{t("log.public")}</option>
        {(detail.data?.players ?? []).map((p) => <option key={p.id} value={p.id}>{t("log.as", { name: p.display_name })}</option>)}
      </select>
      <table className="sk-table sk-log-table">
        <tbody>
          {(events.data ?? []).map((e) => (
            <tr key={e.seq} className={`vis-${String(e.visibility.kind)}`}>
              <td>#{e.seq}</td>
              <td>R{e.round_no}</td>
              <td>{e.type}</td>
              <td>{e.actor ?? ""}</td>
              <td>{String(e.visibility.kind)}{Array.isArray(e.visibility.players) && e.visibility.players.length ? `:${e.visibility.players.join(",")}` : ""}</td>
              <td><pre className="sk-code">{typeof e.payload.text === "string" ? e.payload.text : JSON.stringify(e.payload).slice(0, 600)}</pre></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Section>
  );
}
