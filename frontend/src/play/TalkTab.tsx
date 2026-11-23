import { useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox } from "../ui/components";
import { useAction } from "../ui/hooks";

type Talk = Schemas["TalkOut"];

/** 一场对话：邀请、等待回应、实时说话、结束。对方是玩家还是 NPC，界面上看不出来。 */
function TalkCard({ talk, onChanged }: { talk: Talk; onChanged: () => void }) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const act = useAction();
  const id = talk.id;
  const post = (path: "answer" | "say" | "end", body?: Record<string, unknown>) =>
    void act.run(async () => {
      if (path === "answer") await call(api.POST("/api/talks/{talk_id}/answer", { params: { path: { talk_id: id } }, body: body as { accept: boolean } }));
      if (path === "say") await call(api.POST("/api/talks/{talk_id}/say", { params: { path: { talk_id: id } }, body: { text } }));
      if (path === "end") await call(api.POST("/api/talks/{talk_id}/end", { params: { path: { talk_id: id } } }));
      if (path === "say") setText("");
      onChanged();
    });
  return (
    <div className="sk-card sk-talk">
      <h3>{t("talk.with", { label: talk.other_label })}</h3>
      {talk.status === "invited" && talk.incoming && (
        <div className="sk-echo">
          <p>{t("talk.invited_me", { label: talk.other_label })}</p>
          <button className="sk-primary" disabled={act.busy} onClick={() => post("answer", { accept: true })}>
            {t("talk.accept")}
          </button>
          <button disabled={act.busy} onClick={() => post("answer", { accept: false })}>
            {t("talk.decline")}
          </button>
        </div>
      )}
      {talk.status === "invited" && !talk.incoming && (
        <p className="sk-hint">
          {t("talk.waiting")}{" "}
          <button className="sk-link" onClick={() => post("end")}>
            {t("talk.cancel")}
          </button>
        </p>
      )}
      <div className="sk-log">
        {talk.lines.map((l) => (
          <div key={l.seq} className={l.mine ? "sk-event mine" : "sk-event"}>
            <span className="who">{l.mine ? t("talk.me") : `@${talk.other_label}`}</span>
            <span className="text">{l.text}</span>
          </div>
        ))}
      </div>
      {talk.status === "active" && (
        <>
          <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && text.trim()) { e.preventDefault(); post("say"); } }} />
          <div className="sk-row">
            <button className="sk-primary" disabled={!text.trim() || act.busy} onClick={() => post("say")}>
              {t("talk.send")}
            </button>
            <button disabled={act.busy} onClick={() => post("end")}>
              {t("talk.end")}
            </button>
          </div>
        </>
      )}
      {talk.status === "declined" && <p className="sk-hint">{t("talk.declined")}</p>}
      {talk.status === "ended" && <p className="sk-hint">{t("talk.ended")}</p>}
      <ErrorBox error={act.error} />
    </div>
  );
}

/** “对话”页：进行中的对话在前，结束了的折叠在后。 */
export function TalkTab({ talks, onChanged }: { talks: Talk[]; onChanged: () => void }) {
  const { t } = useI18n();
  const open = talks.filter((x) => x.status === "invited" || x.status === "active");
  const done = talks.filter((x) => x.status === "ended" || x.status === "declined").reverse();
  return (
    <div>
      <p className="sk-hint">{t("talk.hint")}</p>
      {open.length === 0 && <p className="sk-hint">{t("talk.none")}</p>}
      {open.map((x) => (
        <TalkCard key={x.id} talk={x} onChanged={onChanged} />
      ))}
      {done.map((x) => (
        <TalkCard key={x.id} talk={x} onChanged={onChanged} />
      ))}
    </div>
  );
}
