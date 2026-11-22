"""webhook 通知。消息里不含任何游戏内容和 token，只说“第 N 轮已开始”或“有回合待审核”。

payload 同时带 `text`（Slack 等）和 `content`（Discord），以及机器可读的 code 和参数。
发送在后台线程里进行，失败只记日志，不影响游戏。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

import httpx

log = logging.getLogger("smartkeeper.notify")

MESSAGES: dict[str, dict[str, str]] = {
    "round.started": {
        "zh": "【{game}】第 {round} 轮已开始，可以提交行动了。",
        "en": "[{game}] Round {round} has started. You can submit your actions.",
    },
    "round.review": {
        "zh": "【{game}】第 {round} 轮停在待审核，请到控制台处理。",
        "en": "[{game}] Round {round} is waiting for review in the admin console.",
    },
    "game.ended": {
        "zh": "【{game}】这一局结束了。",
        "en": "[{game}] The game has ended.",
    },
}

type Poster = Callable[[str, dict[str, Any]], None]


def _http_post(url: str, payload: dict[str, Any]) -> None:
    httpx.post(url, json=payload, timeout=5.0).raise_for_status()


class WebhookNotifier:
    def __init__(self, post: Poster = _http_post, background: bool = True) -> None:
        self._post = post
        self._background = background

    @staticmethod
    def render(code: str, lang: str, **params: str | int) -> str:
        table = MESSAGES[code]
        return table.get(lang, table["en"]).format(**params)

    def send(self, url: str | None, code: str, lang: str, **params: str | int) -> None:
        if not url:
            return
        payload: dict[str, Any] = {"code": code, "params": params}
        payload["text"] = payload["content"] = self.render(code, lang, **params)

        def run() -> None:
            try:
                self._post(url, payload)
            except Exception as e:
                log.warning("webhook %s failed: %s", code, e)

        if self._background:
            threading.Thread(target=run, daemon=True).start()
        else:
            run()
