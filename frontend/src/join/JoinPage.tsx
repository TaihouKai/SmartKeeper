import { useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, LangSwitch, Section } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";
import { HandbookProvider, Markdown } from "../ui/markdown";
import { DocsTab, useDocs } from "../ui/docs";
import { CharacterForm } from "./CharacterForm";
import { CharacterPicker, type Origin } from "./Library";

/** /join：阅读规则，按剧本抽取或选择身份，按模板填写并提交角色卡，查看 KP 的审核意见。 */
export function JoinPage() {
  const { t } = useI18n();
  const docs = useDocs();
  const invalid = new URLSearchParams(window.location.search).has("invalid");
  const me = usePoll(() => call(api.GET("/api/me")), 10_000);
  const rules = usePoll(() => call(api.GET("/api/rules")), 600_000);
  const events = usePoll(() => call(api.GET("/api/events")), 10_000);
  const choose = useAction();
  const [editing, setEditing] = useState(false);
  // 选角色还是在建卡：已经有草稿或者提交过的直接建卡；载入角色库的角色时记着它（提交时可以更新）
  const draft = usePoll(() => call(api.GET("/api/character/draft")), 3_600_000);
  const [picking, setPicking] = useState<boolean | null>(null);
  const [origin, setOrigin] = useState<Origin | null>(null);
  const [formKey, setFormKey] = useState(0);

  if (invalid || (me.error && !me.data)) {
    return (
      <main className="sk-page">
        <h1>{t("app.title")}</h1>
        <p>{t(invalid ? "join.invalid" : "join.no_session")}</p>
        <p>
          <a className="sk-button sk-primary" href="/">
            {t("join.to_lobby")}
          </a>
        </p>
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
    <main className="sk-page sk-join">
      <header className="sk-top cf-top">
        <h1>{m.game_name}</h1>
        <NickName name={m.display_name} onSaved={refresh} />
        <a href="/rulebook" target="_blank" rel="noreferrer">
          {t("handbook.title")}
        </a>
        <a href="/rulebook#scenario" target="_blank" rel="noreferrer">
          {t("handbook.scenario")}
        </a>
        {docs && (
          <button type="button" className="sk-link" onClick={() => docs.open()}>
            {t("docs.title")}
          </button>
        )}
        <DocsTab />
        <LangSwitch onChange={(l) => void api.POST("/api/lang", { body: { lang: l } })} />
      </header>

      {m.game_status === "running" || m.game_status === "ended" ? (
        <p className="sk-card">
          {t("join.game_started")} <a href="/play">{t("join.go_play")}</a>
        </p>
      ) : null}

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
        <>
          {status !== "none" && <p className="sk-status">{t(`join.status.${status}`)}</p>}
          {lastReview && (
            <div className={lastReview.type === "character_rejected" ? "sk-card sk-warn" : "sk-card"}>
              <strong>{t("join.review")}</strong>
              <p>{String(lastReview.payload.comments ?? "")}</p>
            </div>
          )}
          {(status === "none" || status === "rejected" || editing) && m.game_status === "characters" ? (
            <HandbookProvider text={r.handbook} href="/rulebook">
              {(() => {
                const hasDraft = Array.isArray(draft.data?.sheets) && (draft.data?.sheets as unknown[]).length > 0;
                const pick = picking ?? (status === "none" && !hasDraft);
                if (!draft.data && !draft.error) return <p>{t("common.loading")}</p>;
                return (
                  <>
                    <details className="sk-card scen-intro" open={pick}>
                      <summary>{t("lib.scenario")}</summary>
                      <Markdown text={r.scenario} />
                    </details>
                    {pick ? (
                      <CharacterPicker
                        onNew={() => {
                          setOrigin(null);
                          setPicking(false);
                          setFormKey((k) => k + 1);
                        }}
                        onPick={(sheets, o) =>
                          void choose.run(async () => {
                            // 载入：当成草稿放进建卡表单，可以再改。只留这套规则书要玩家建的卡，缺的部分补齐
                            const wanted = new Set((r.player_entities as unknown as { template: string }[]).map((x) => x.template));
                            const clean = (Array.isArray(sheets) ? (sheets as { template: string; sheet: Record<string, unknown> }[]) : [])
                              .filter((x) => wanted.has(x.template))
                              .map((x) => ({ template: x.template, sheet: { name: "", fields: {}, groups: {}, preset_fields: {}, ...(x.sheet ?? {}) } }));
                            await call(api.PUT("/api/character/draft", { body: { sheets: clean as never } }));
                            setOrigin(o);
                            setPicking(false);
                            setFormKey((k) => k + 1);
                          })
                        }
                      />
                    ) : (
                      <CharacterForm
                        key={formKey}
                        templates={r.templates as unknown as Schemas["EntityTemplate"][]}
                        playerEntities={r.player_entities as unknown as { template: string; min: number; max: number }[]}
                        params={r.params}
                        checks={r.checks}
                        origin={origin}
                        onPickAnother={() => setPicking(true)}
                        onSubmitted={() => {
                          setEditing(false);
                          refresh();
                        }}
                      />
                    )}
                  </>
                );
              })()}
            </HandbookProvider>
          ) : status === "submitted" ? (
            <p>{t("join.waiting_review")}</p>
          ) : null}
        </>
      )}
    </main>
  );
}

/** 玩家昵称（不是角色名）：点“改”就地改。 */
function NickName({ name, onSaved }: { name: string; onSaved: () => void }) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(name);
  const act = useAction();
  if (!editing)
    return (
      <span>
        {t("join.hello", { name })}{" "}
        <button className="sk-link" onClick={() => { setValue(name); setEditing(true); }}>
          {t("join.rename")}
        </button>
      </span>
    );
  const save = () =>
    void act.run(async () => {
      await call(api.POST("/api/me/name", { body: { name: value } }));
      setEditing(false);
      onSaved();
    });
  return (
    <span className="sk-row">
      <input value={value} maxLength={64} placeholder={t("lobby.name_ph")} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.key === "Enter" && value.trim() && save()} />
      <button className="sk-primary" disabled={act.busy || !value.trim()} onClick={save}>
        {t("common.save")}
      </button>
      <button className="sk-link" onClick={() => setEditing(false)}>
        {t("common.cancel")}
      </button>
      <ErrorBox error={act.error} />
    </span>
  );
}
