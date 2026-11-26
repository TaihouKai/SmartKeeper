import { useEffect } from "react";
import { api, call, gamePath } from "../api/client";
import { useI18n } from "../i18n";
import { usePoll } from "../ui/hooks";
import { PlayPage } from "../play/PlayPage";
import { JoinPage } from "./JoinPage";

/** 一局自己的网址 /g/<局 id>：建角阶段是建卡页，开局以后是游戏页（开局时自动换过去）。 */
export function GamePage() {
  const { t } = useI18n();
  const me = usePoll(() => call(api.GET("/api/me")), 15_000);
  if (me.error && !me.data) return <JoinPage />; // 没有这一局的座位：建卡页会显示“回到首页”
  if (!me.data) return <main className="sk-page">{t("common.loading")}</main>;
  return me.data.game_status === "running" || me.data.game_status === "ended" ? <PlayPage /> : <JoinPage />;
}

/** 旧的 /join、/play：转到这个浏览器当前在玩的那一局自己的网址。 */
export function ToCurrentGame() {
  const { t } = useI18n();
  const me = usePoll(() => call(api.GET("/api/me")), 3_600_000);
  useEffect(() => {
    if (me.data) window.location.replace(gamePath(me.data.game_id));
  }, [me.data]);
  if (me.error && !me.data) return <JoinPage />;
  return <main className="sk-page">{t("common.loading")}</main>;
}
