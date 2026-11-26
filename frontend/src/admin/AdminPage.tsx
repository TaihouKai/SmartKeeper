import { useState } from "react";
import { api, call } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, LangSwitch, Tabs } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";
import { GamesPanel, MaterialsPanel } from "./GamesPanel";
import { LogPanel } from "./LogPanel";
import { RulesPanel } from "./RulesPanel";
import { LlmPanel, StatePanel } from "./StatePanel";

type Panel = "rules" | "materials" | "games" | "log" | "state" | "llm";

function Login({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const [pw, setPw] = useState("");
  const act = useAction();
  const enabled = usePoll(() => call(api.GET("/api/admin/enabled")), 600_000);
  if (enabled.data && !enabled.data.enabled) return <p>{t("admin.disabled")}</p>;
  return (
    <form
      className="sk-card"
      onSubmit={(e) => {
        e.preventDefault();
        void act.run(async () => {
          await call(api.POST("/api/admin/login", { body: { password: pw } }));
          onDone();
        });
      }}
    >
      <label>
        {t("admin.password")}
        <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus />
      </label>
      <button className="sk-primary" type="submit" disabled={act.busy}>
        {t("admin.login")}
      </button>
      <ErrorBox error={act.error} />
    </form>
  );
}

/** /admin：管理控制台。只有管理员能进；所有管理工作都在这里做。 */
export function AdminPage() {
  const { t } = useI18n();
  const session = usePoll(async () => {
    const r = await api.GET("/api/admin/session");
    return r.response.ok;
  }, 300_000);
  const [panel, setPanel] = useState<Panel>("games");
  const [game, setGame] = useState<string | null>(null);
  if (session.data === null) return <main className="sk-page">{t("common.loading")}</main>;
  if (!session.data) {
    return (
      <main className="sk-page">
        <h1>{t("admin.title")}</h1>
        <Login onDone={() => void session.refresh()} />
      </main>
    );
  }
  return (
    <main className={panel === "rules" ? "sk-page sk-admin sk-admin-full" : "sk-page sk-admin"}>
      <header className="sk-top">
        <h1>{t("admin.title")}</h1>
        <LangSwitch />
        <button className="sk-link" onClick={() => void api.POST("/api/admin/logout").then(() => session.refresh())}>
          {t("admin.logout")}
        </button>
      </header>
      <Tabs
        tabs={[
          { key: "games", label: t("admin.panel.games") },
          { key: "log", label: t("admin.panel.log") },
          { key: "state", label: t("admin.panel.state") },
          { key: "llm", label: t("admin.panel.llm") },
          { key: "rules", label: t("admin.panel.rules") },
          { key: "materials", label: t("admin.panel.materials") },
        ]}
        active={panel}
        onChange={setPanel}
      />
      {panel === "rules" && <RulesPanel />}
      {panel === "materials" && <MaterialsPanel />}
      {panel === "games" && <GamesPanel selected={game} onSelect={setGame} />}
      {(panel === "log" || panel === "state" || panel === "llm") && !game && <p>{t("admin.pick_game")}</p>}
      {panel === "state" && game && <StatePanel gameId={game} />}
      {panel === "llm" && game && <LlmPanel gameId={game} />}
      {panel === "log" && game && <LogPanel gameId={game} />}
    </main>
  );
}
