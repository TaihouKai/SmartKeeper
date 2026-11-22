import { AdminPage } from "./admin/AdminPage";
import { useI18n } from "./i18n";
import { JoinPage } from "./join/JoinPage";
import { PlayPage } from "./play/PlayPage";
import "./ui/style.css";

export function App() {
  const { t } = useI18n();
  const path = window.location.pathname;
  if (path.startsWith("/admin")) return <AdminPage />;
  if (path.startsWith("/join")) return <JoinPage />;
  if (path.startsWith("/play")) return <PlayPage />;
  return (
    <main className="sk-page">
      <h1>{t("app.title")}</h1>
      <p>{t("app.landing")}</p>
      <p>
        <a href="/play">{t("app.to_play")}</a> · <a href="/admin">{t("app.to_admin")}</a>
      </p>
    </main>
  );
}
