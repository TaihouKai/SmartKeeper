import { useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox } from "../ui/components";
import { useAction } from "../ui/hooks";
import { EventRow, prettyMentions, type Ev } from "./events";

export interface Mentionable {
  ref: string;
  label: string;
}

/** KP 页：行动框（声明本轮行动，提交前解析确认）和聊天框（提问澄清）。每轮的反馈也显示在这里。 */
export function KpTab({
  events,
  status,
  draft,
  setDraft,
  quotes,
  setQuotes,
  mentionables,
  onChanged,
}: {
  events: Ev[];
  status: Schemas["StatusOut"] | null;
  draft: string;
  setDraft: (s: string) => void;
  quotes: number[];
  setQuotes: (q: number[]) => void;
  mentionables: Mentionable[];
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const [echo, setEcho] = useState<Schemas["ActionEcho"] | null>(null);
  const [question, setQuestion] = useState("");
  const parse = useAction();
  const confirm = useAction();
  const ask = useAction();
  const collecting = status?.game_status === "running" && status.phase === "collecting";
  const kpEvents = events.filter((e) => ["pm_kp", "feedback", "action_declared", "round_opened"].includes(e.type));
  const myDecl = [...events].reverse().find((e) => e.type === "action_declared" && e.round_no === status?.round);

  const doParse = () =>
    void parse.run(async () => {
      setEcho(await call(api.POST("/api/action/parse", { body: { text: draft } })));
    });
  const doConfirm = () =>
    void confirm.run(async () => {
      if (!echo) return;
      const intent = { ...echo.intent, quotes: Array.from(new Set([...(echo.intent.quotes ?? []), ...quotes])) };
      await call(api.POST("/api/action", { body: { text: echo.text, intent } }));
      setEcho(null);
      setDraft("");
      setQuotes([]);
      onChanged();
    });
  const doAsk = () =>
    void ask.run(async () => {
      await call(api.POST("/api/kp/chat", { body: { text: question } }));
      setQuestion("");
      onChanged();
    });

  return (
    <div className="sk-kp">
      <div className="sk-log">
        {kpEvents.map((e) => (
          <EventRow key={e.seq} e={e} onQuote={(s) => setQuotes(Array.from(new Set([...quotes, s])))} />
        ))}
      </div>

      <div className="sk-box">
        <h3>{t("kp.action_box")}</h3>
        <p className="sk-hint">{t("kp.action_hint")}</p>
        {status?.me_submitted && myDecl && (
          <p className="sk-card">
            {t("kp.submitted_already")} {prettyMentions(String(myDecl.payload.text ?? ""))}
          </p>
        )}
        <textarea rows={4} value={draft} disabled={!collecting} onChange={(e) => { setDraft(e.target.value); setEcho(null); }} />
        <div className="sk-row">
          <select
            value=""
            disabled={!collecting}
            onChange={(e) => {
              const m = mentionables.find((x) => x.ref === e.target.value);
              if (m) setDraft(`${draft}@[${m.label}](${m.ref}) `);
            }}
          >
            <option value="">{t("kp.insert_mention")}</option>
            {mentionables.map((m) => (
              <option key={m.ref} value={m.ref}>
                @{m.label}
              </option>
            ))}
          </select>
          {quotes.map((q) => (
            <button key={q} className="sk-chip" onClick={() => setQuotes(quotes.filter((x) => x !== q))}>
              {t("kp.quote_chip", { seq: String(q) })} ×
            </button>
          ))}
          <button className="sk-primary" disabled={!collecting || !draft.trim() || parse.busy} onClick={doParse}>
            {parse.busy ? t("common.working") : t("kp.parse")}
          </button>
        </div>
        <ErrorBox error={parse.error} />
        {echo && (
          <div className="sk-echo">
            <strong>{t("kp.understood_as")}</strong>
            <ul>
              {echo.items.map((it, i) => (
                <li key={i}>
                  <b>{it.actor_label}</b> · {it.verb}
                  {it.targets.length > 0 && <> → {it.targets.map((x) => (x.kind === "entity" ? `@${x.label}` : x.label || t("kp.a_point"))).join(", ")}</>}
                  {it.destination_label && <> ⇒ {it.destination_label}</>}
                  {it.detail && <div className="sk-hint">{prettyMentions(it.detail)}</div>}
                </li>
              ))}
            </ul>
            {echo.unresolved.length > 0 && (
              <div className="sk-warn">
                {t("kp.unresolved")} {echo.unresolved.join(", ")}
              </div>
            )}
            <div className="sk-row">
              <button className="sk-primary" disabled={confirm.busy || echo.unresolved.length > 0 || echo.items.length === 0} onClick={doConfirm}>
                {t("kp.confirm")}
              </button>
              <button onClick={() => setEcho(null)}>{t("kp.edit")}</button>
            </div>
            <ErrorBox error={confirm.error} />
          </div>
        )}
      </div>

      <div className="sk-box">
        <h3>{t("kp.chat_box")}</h3>
        <p className="sk-hint">{t("kp.chat_hint")}</p>
        <textarea rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} />
        <button disabled={!question.trim() || ask.busy} onClick={doAsk}>
          {t("kp.ask")}
        </button>
        <ErrorBox error={ask.error} />
      </div>
    </div>
  );
}
