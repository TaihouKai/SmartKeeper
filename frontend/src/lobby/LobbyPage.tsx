import { useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, LangSwitch } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";

type Game = Schemas["LobbyGame"];

/** 首页：房间列表。建角阶段的局填个名字就能加入；加入过的局点“继续”回去。 */
export function LobbyPage() {
  const { t } = useI18n();
  const games = usePoll(() => call(api.GET("/api/lobby")), 10_000);
  const [joined, setJoined] = useState<string | null>(null);
  const list = games.data ?? [];
  return (
    <main className="sk-page">
      <header className="sk-top">
        <h1>{t("app.title")}</h1>
        <LangSwitch />
      </header>
      <p>{t("lobby.intro")}</p>
      {joined && (
        <div className="sk-card">
          <p>{t("lobby.joined")}</p>
          <p className="sk-hint">{t("lobby.link_hint")}</p>
          <input readOnly value={joined} onFocus={(e) => e.target.select()} />
          <p>
            <button className="sk-primary" onClick={() => (window.location.href = "/join")}>
              {t("lobby.go")}
            </button>
          </p>
        </div>
      )}
      <ErrorBox error={games.error} />
      {games.data && list.length === 0 && <p className="sk-hint">{t("lobby.empty")}</p>}
      {list.map((g) => (
        <Room
          key={g.id}
          g={g}
          onJoined={(link) => {
            setJoined(link);
            void games.refresh();
            window.scrollTo(0, 0);
          }}
        />
      ))}
      <p className="sk-hint">
        <a href="/admin">{t("app.to_admin")}</a>
      </p>
    </main>
  );
}

function Room({ g, onJoined }: { g: Game; onJoined: (link: string) => void }) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const act = useAction();
  const enter = () =>
    void act.run(async () => {
      await call(api.POST("/api/lobby/enter", { body: { game_id: g.id } }));
      window.location.href = g.status === "running" ? "/play" : "/join";
    });
  const join = () =>
    void act.run(async () => {
      const r = await call(api.POST("/api/lobby/join", { body: { game_id: g.id, name } }));
      onJoined(r.link);
    });
  return (
    <div className="sk-card">
      <div className="sk-row">
        <strong>{g.name}</strong>
        <span className="sk-hint">
          {t(`lobby.status.${g.status}`)} · {t("lobby.players", { n: String(g.players) })}
        </span>
        <a href={`/rulebook?game=${encodeURIComponent(g.id)}`} target="_blank" rel="noreferrer">
          {t("handbook.title")}
        </a>
      </div>
      {g.seat ? (
        <div className="sk-row">
          <span>{t(g.active ? "lobby.you_active" : "lobby.you", { name: g.seat })}</span>
          <button className="sk-primary" disabled={act.busy} onClick={enter}>
            {t("lobby.continue")}
          </button>
        </div>
      ) : g.joinable ? (
        <div className="sk-row">
          <input value={name} maxLength={64} placeholder={t("lobby.name_ph")} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && name.trim() && join()} />
          <button className="sk-primary" disabled={act.busy || !name.trim()} onClick={join}>
            {t("lobby.join")}
          </button>
        </div>
      ) : (
        <p className="sk-hint">{t("lobby.started")}</p>
      )}
      <ErrorBox error={act.error} />
    </div>
  );
}
