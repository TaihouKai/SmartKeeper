import { useState } from "react";
import { api, call } from "../api/client";
import { useI18n } from "../i18n";
import { Section } from "../ui/components";
import { usePoll } from "../ui/hooks";

/** “审核”面板：裁定 JSON、骰子和空间查询结果、各玩家反馈草稿；可编辑、单份重写、发布。 */
/** 本轮在等谁应对；一直不上线的玩家，管理员可以替他选（不是规则，只是不让整局停住）。 */
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
