import { AdminPage } from "./admin/AdminPage";
import { JoinPage } from "./join/JoinPage";
import { LobbyPage } from "./lobby/LobbyPage";
import { PlayPage } from "./play/PlayPage";
import "./ui/style.css";

export function App() {
  const path = window.location.pathname;
  if (path.startsWith("/admin")) return <AdminPage />;
  if (path.startsWith("/join")) return <JoinPage />;
  if (path.startsWith("/play")) return <PlayPage />;
  return <LobbyPage />;
}
