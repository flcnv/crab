from typing import Any

from anthropic.types.beta import BetaMessage


def message(
    *content: dict[str, Any],
    text: str | None = None,
    model: str = "claude-sonnet-5-5",
    stop_reason: str | None = None,
    stop_details: dict[str, Any] | None = None,
) -> BetaMessage:
    blocks = list(content) + ([{"type": "text", "text": text}] if text is not None else [])
    if stop_reason is None:
        stop_reason = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
    return BetaMessage.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": blocks,
            "stop_reason": stop_reason,
            "stop_details": stop_details,
            "stop_sequence": None,
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 300,
                "cache_read_input_tokens": 2000,
                "cache_creation_input_tokens": 0,
            },
        }
    )


def tool_use(name: str, tool_input: dict[str, Any], id: str = "toolu_1") -> dict[str, Any]:  # noqa: A002
    return {"type": "tool_use", "id": id, "name": name, "input": tool_input}


class FakeMessages:
    def __init__(self, replies: list[BetaMessage | Exception]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> BetaMessage:
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeClient:
    def __init__(self, replies: list[BetaMessage | Exception]) -> None:
        self.messages = FakeMessages(replies)
        self.beta = self
