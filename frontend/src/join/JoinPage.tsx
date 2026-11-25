import { useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, LangSwitch, MarkdownView, Section } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";
import { CharacterForm } from "./CharacterForm";

/** /join：阅读规则，按剧本抽取或选择身份，按模板填写并提交角色卡，查看 KP 的审核意见。 */
export function JoinPage() {
  const { t } = useI18n();
  const invalid = new URLSearchParams(window.location.search).has("invalid");
  const me = usePoll(() => call(api.GET("/api/me")), 10_000);
  const rules = usePoll(() => call(api.GET("/api/rules")), 600_000);
  const events = usePoll(() => call(api.GET("/api/events")), 10_000);
  const choose = useAction();
  const [showRules, setShowRules] = useState(false);
  const [editing, setEditing] = useState(false);

  if (invalid || (me.error && !me.data)) {
    return (
      <main className="sk-page">
        <h1>{t("app.title")}</h1>
        <p>{t(invalid ? "join.invalid" : "join.no_session")}</p>
      </main>
    );
  }
  if (!me.data || !rules.data) return <main className="sk-page">{t("common.loading")}</main>;
  const m = me.data;
  const r = rules.data;
  const evs = events.data ?? [];
  const identity = evs.find((e) => e.type === "identity_assigned");
  const reviews = evs.filter((e) => e.type === "character_rejected" || e.type === "character_approved");
  const lastReview = reviews[reviews.length - 1];
  const needIdentity = r.identities.options.length > 0 && !identity;
  const status = m.character_status;
  const refresh = () => {
    void me.refresh();
    void events.refresh();
  };

  return (
    <main className="sk-page">
      <header className="sk-top">
        <h1>{m.game_name}</h1>
        <span>{t("join.hello", { name: m.display_name })}</span>
        <LangSwitch onChange={(l) => void api.POST("/api/lang", { body: { lang: l } })} />
      </header>

      {m.game_status === "running" || m.game_status === "ended" ? (
        <p className="sk-card">
          {t("join.game_started")} <a href="/play">{t("join.go_play")}</a>
        </p>
      ) : null}

      <Section
        title={t("join.rules")}
        actions={
          <button className="sk-link" onClick={() => setShowRules(!showRules)}>
            {t(showRules ? "common.hide" : "common.show")}
          </button>
        }
      >
        {showRules && (
          <>
            <MarkdownView text={r.scenario} />
            <hr />
            <MarkdownView text={r.rulebook} />
          </>
        )}
      </Section>

      {r.identities.options.length > 0 && (
        <Section title={t("join.identity")}>
          {identity ? (
            <div className="sk-card">
              <strong>{String(identity.payload.name ?? "")}</strong>
              <p>{String(identity.payload.description ?? "")}</p>
            </div>
          ) : r.identities.mode === "draw" ? (
            <button className="sk-primary" disabled={choose.busy} onClick={() => void choose.run(async () => {
              await call(api.POST("/api/identity", { body: {} }));
              refresh();
            })}>
              {t("join.draw")}
            </button>
          ) : (
            <div className="sk-list">
              {r.identities.options.map((o: Schemas["Identity"]) => (
                <button key={o.id} disabled={choose.busy} onClick={() => void choose.run(async () => {
                  await call(api.POST("/api/identity", { body: { choice: o.id } }));
                  refresh();
                })}>
                  <strong>{o.name}</strong> {o.description}
                </button>
              ))}
            </div>
          )}
          <ErrorBox error={choose.error} />
        </Section>
      )}

      {!needIdentity && (
        <Section title={t("join.character")}>
          <p className="sk-status">{t(`join.status.${status}`)}</p>
          {lastReview && (
            <div className={lastReview.type === "character_rejected" ? "sk-card sk-warn" : "sk-card"}>
              <strong>{t("join.review")}</strong>
              <p>{String(lastReview.payload.comments ?? "")}</p>
            </div>
          )}
          {(status === "none" || status === "rejected" || editing) && m.game_status === "characters" ? (
            <CharacterForm
              templates={r.templates as unknown as Schemas["EntityTemplate"][]}
              playerEntities={r.player_entities as unknown as { template: string; min: number; max: number }[]}
              onSubmitted={() => {
                setEditing(false);
                refresh();
              }}
            />
          ) : status === "submitted" ? (
            <p>{t("join.waiting_review")}</p>
          ) : null}
        </Section>
      )}
    </main>
  );
}
