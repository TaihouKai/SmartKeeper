import type { Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { Markdown } from "../ui/markdown";
import { factText } from "./intel";

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

/** 一条事件写成什么：谁说的、内容、内容是不是 Markdown、样式（反馈、行动、系统消息……）。 */
export type Described = { who: string; body: string; md: boolean; cls: string };

export function describeEvent(e: Ev, t: (k: string, p?: Record<string, string>) => string): Described {
  let who = "";
  if (e.actor === "kp") who = t("event.kp");
  else if (e.actor === "me") who = t("event.me");
  else if (e.actor === "anonymous") who = t("event.anonymous");
  else if (e.actor === "player") who = e.actor_name ?? "?";
  let body: string;
  let md = false; // 审核意见是 Markdown
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
      md = true;
      who = t(e.type === "character_approved" ? "event.approved" : "event.rejected");
      break;
    case "character_submitted":
      body = t("event.submitted");
      cls += " sys";
      break;
    case "reaction_requested": {
      const entry = String(e.payload.entry ?? "");
      const by = e.payload.who;
      // 不暴露名字的攻击：只知道挨了一下
      const key = entry ? "react.by" : "react.by_hidden";
      body = typeof by === "string" && by ? t(key, { who: by, entry, defender: "" }) : t(`${key === "react.by" ? "react.by_unknown" : "react.by_unknown_hidden"}`, { entry, defender: "" });
      who = t("event.react");
      cls += " feedback";
      break;
    }
    case "entry_noticed": {
      const entry = typeof e.payload.entry === "string" ? e.payload.entry : "";
      const by = e.payload.who;
      // 不暴露名字的技能（例如平时挥剑）：只知道有人用了点什么
      const key = entry ? "event.noticed" : "event.noticed_unknown";
      body = typeof by === "string" && by ? t(`${key}_who`, { who: by, entry }) : t(key, { entry });
      who = t("event.sense");
      break;
    }
    case "alliance_notice": {
      const kind = String(e.payload.kind ?? "");
      body = t(`alliance.n.${kind}${e.payload.mine ? "_mine" : ""}`, { who: String(e.payload.label ?? "") });
      who = t("event.alliance");
      break;
    }
    case "intel_gained": {
      const facts = (Array.isArray(e.payload.facts) ? e.payload.facts : []) as Schemas["IntelFact"][];
      body = t("intel.gained", { who: String(e.payload.label ?? ""), facts: facts.map((f) => factText(f, t)).join(t("intel.list_sep")) });
      who = t("event.intel");
      break;
    }
    default:
      body = eventText(e);
  }
  if (e.type === "pm_kp" && e.payload.kind === "opening") who = t("event.opening");
  return { who, body, md, cls };
}

/** 一条事件的显示：系统事件用消息代码渲染，其余显示原文。可选“引用”按钮。 */
export function EventRow({ e, onQuote }: { e: Ev; onQuote?: (seq: number) => void }) {
  const { t } = useI18n();
  const { who, body, md, cls } = describeEvent(e, t);
  return (
    <div className={cls}>
      {who && <span className="who">{who}</span>}
      {md ? (
        <div className="text md">
          <Markdown text={body} />
        </div>
      ) : (
        <span className="text">{body}</span>
      )}
      {onQuote && (
        <button className="sk-link quote" onClick={() => onQuote(e.seq)} title={t("event.quote")}>
          {t("event.quote")}
        </button>
      )}
    </div>
  );
}
