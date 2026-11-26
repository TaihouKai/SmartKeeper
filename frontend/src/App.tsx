import { AdminPage } from "./admin/AdminPage";
import { JoinPage } from "./join/JoinPage";
import { LobbyPage } from "./lobby/LobbyPage";
import { PlayPage } from "./play/PlayPage";
import { RulebookPage } from "./rulebook/RulebookPage";
import { DocsProvider, loadDocs } from "./ui/docs";
import "./ui/style.css";

void loadDocs();

function Page() {
  const path = window.location.pathname;
  if (path.startsWith("/admin")) return <AdminPage />;
  if (path.startsWith("/join")) return <JoinPage />;
  if (path.startsWith("/play")) return <PlayPage />;
  if (path.startsWith("/rulebook")) return <RulebookPage part="handbook" />;
  if (path.startsWith("/scenario")) return <RulebookPage part="scenario" />;
  return <LobbyPage />;
}

export function App() {
  return (
    <DocsProvider>
      <Page />
    </DocsProvider>
  );
}
