import { AdminPage } from "./admin/AdminPage";
import { JoinPage } from "./join/JoinPage";
import { LobbyPage } from "./lobby/LobbyPage";
import { BooksRoute } from "./books/BooksPage";
import { RulebookPage } from "./rulebook/RulebookPage";
import { DocsProvider, loadDocs } from "./ui/docs";
import { GamePage, ToCurrentGame } from "./join/GamePage";
import "./ui/style.css";

void loadDocs();

function Page() {
  const path = window.location.pathname;
  if (path.startsWith("/admin")) return <AdminPage />;
  // 每一局自己的网址；旧的 /join、/play 转到当前在玩的那一局的网址（作废的邀请链接照旧显示提示）
  if (path.startsWith("/g/")) return <GamePage />;
  if (path.startsWith("/join")) return new URLSearchParams(window.location.search).has("invalid") ? <JoinPage /> : <ToCurrentGame />;
  if (path.startsWith("/play")) return <ToCurrentGame />;
  if (path.startsWith("/rulebook")) return <RulebookPage part="handbook" />;
  if (path === "/books" || path.startsWith("/books/")) return <BooksRoute />;
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
