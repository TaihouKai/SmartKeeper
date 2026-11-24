import type { Schemas } from "../api/client";
import { useI18n } from "../i18n";

export type Ev = Schemas["EventOut"];

const MENTION = /@\[([^\]\n]{1,80})\]\(([A-Za-z0-9_:.,-]{1,80})\)/g;

/** 显示时把 `@[文字](ref)` 换成 `@文字`。 */
export function prettyMentions(text: string): string {
  return text.replace(MENTION, (_m, label: string) => `@${label}`);
}

export function eventText(e: Ev): string {
  const text = e.payload.text;
  return typeof text === "string" ? prettyMentions(text) : "";
}

/** 一条事件的显示：系统事件用消息代码渲染，其余显示原文。可选“引用”按钮。 */
export function EventRow({ e, onQuote }: { e: Ev; onQuote?: (seq: number) => void }) {
  const { t } = useI18n();
  let who = "";
  if (e.actor === "kp") who = t("event.kp");
  else if (e.actor === "me") who = t("event.me");
  else if (e.actor === "anonymous") who = t("event.anonymous");
  else if (e.actor === "player") who = e.actor_name ?? "?";
  let body: string;
  let cls = "sk-event";
  switch (e.type) {
    case "round_opened":
      body = t("event.round_opened", { round: String(e.payload.round ?? "") });
      cls += " sys";
      break;
    case "round_closed":
      body = t("event.round_closed", { round: String(e.payload.round ?? "") });
      cls += " sys";
      break;
    case "feedback":
      body = eventText(e);
      cls += " feedback";
      who = t("event.feedback");
      break;
    case "action_declared":
      body = eventText(e);
      cls += " action";
      who = t("event.my_action");
      break;
    case "identity_assigned":
      body = `${String(e.payload.name ?? "")} — ${String(e.payload.description ?? "")}`;
      who = t("event.identity");
      break;
    case "character_approved":
    case "character_rejected":
      body = String(e.payload.comments ?? "");
      who = t(e.type === "character_approved" ? "event.approved" : "event.rejected");
      break;
    case "character_submitted":
      body = t("event.submitted");
      cls += " sys";
      break;
    case "entry_noticed": {
      const entry = String(e.payload.entry ?? "");
      const by = e.payload.who;
      body = typeof by === "string" && by ? t("event.noticed_who", { who: by, entry }) : t("event.noticed", { entry });
      who = t("event.sense");
      break;
    }
    default:
      body = eventText(e);
  }
  if (e.type === "pm_kp" && e.payload.kind === "opening") who = t("event.opening");
  return (
    <div className={cls}>
      {who && <span className="who">{who}</span>}
      <span className="text">{body}</span>
      {onQuote && (
        <button className="sk-link quote" onClick={() => onQuote(e.seq)} title={t("event.quote")}>
          {t("event.quote")}
        </button>
      )}
    </div>
  );
}
