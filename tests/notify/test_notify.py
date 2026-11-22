from typing import Any

from smartkeeper.notify import MESSAGES, WebhookNotifier


def test_sends_without_game_content() -> None:
    sent: list[tuple[str, dict[str, Any]]] = []
    n = WebhookNotifier(lambda url, p: sent.append((url, p)), background=False)
    n.send("http://hook", "round.started", "zh", game="测试局", round=3)
    n.send(None, "round.started", "zh", game="x", round=1)  # 没配置就不发
    assert len(sent) == 1
    url, payload = sent[0]
    assert url == "http://hook"
    assert payload["text"] == payload["content"] == "【测试局】第 3 轮已开始，可以提交行动了。"
    assert payload["code"] == "round.started"


def test_failure_is_swallowed() -> None:
    def boom(url: str, p: dict[str, Any]) -> None:
        raise RuntimeError("down")

    WebhookNotifier(boom, background=False).send(
        "http://x", "round.review", "en", game="g", round=1
    )


def test_every_message_has_both_languages() -> None:
    for table in MESSAGES.values():
        assert set(table) == {"zh", "en"}
