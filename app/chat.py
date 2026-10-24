"""术语助手：右侧对话框的后端。

职责被刻意收窄——只回答「翻译」和「中医术语」两类问题，其余话题
礼貌拒绝。这个限制不是摆设：课堂上学生问的东西越杂，回复越长，
越容易把注意力从字幕上带走。

它能做一件实事：根据对话调整识别热词。比如用户说「把太阳伤寒加进
热词」，模型会调用 update_hotwords 工具，而不是嘴上答应。
"""
from __future__ import annotations

import asyncio
import json
import logging

from . import config
from .glossary import Glossary
from .lexicon import Lexicon

log = logging.getLogger("chat")

SYSTEM = """你是「中医课堂实时字幕」这个工具内置的助手。

你的职责只有两类问题：
1. 翻译相关：某个词为什么这样译、有没有更准的译法、中英表达差异。
2. 中医术语：某条术语的含义、出处、相近术语的区别。

除此之外的一切（闲聊、写代码、时事、生活建议等），一律简短礼貌地
说明你只负责本工具的翻译与术语问题，然后请对方换个问题。不要假装
能回答，也不要展开无关内容。

回答要短。这是课堂场景，用户正在看字幕，没人有空读长文——
两三句话说清即可，必要时举一个例子。

你有权调整语音识别的热词表。当用户明确要求增加或减少热词时
（例如「把XX加进热词」「别识别成XX」），调用 update_hotwords 工具，
不要只说「好的」。工具执行完再用一句话确认结果。

当前热词状况：{hotword_state}
"""

TOOLS = [{
    "type": "function",
    "function": {
        "name": "update_hotwords",
        "description": "增删语音识别的热词。热词会让识别引擎更倾向于把发音听成这些词。",
        "parameters": {
            "type": "object",
            "properties": {
                "add": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要加入的热词，中文术语原文",
                },
                "remove": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要移除的热词",
                },
            },
            "required": ["add", "remove"],
        },
    },
}]


class ChatService:
    MAX_TURNS = 12        # 保留最近几轮，避免上下文无限增长

    def __init__(self, lexicon: Lexicon, glossary: Glossary):
        self.lexicon = lexicon
        self.glossary = glossary
        self.history: list[dict] = []
        self._client = None
        self._lock = asyncio.Lock()

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=config.DEEPSEEK_API_KEY,
                base_url=config.DEEPSEEK_BASE_URL,
            )
        return self._client

    def reset(self) -> None:
        self.history.clear()

    async def ask(self, message: str) -> dict:
        message = (message or "").strip()
        if not message:
            return {"reply": "", "changed": None}

        if not config.DEEPSEEK_API_KEY:
            return {"reply": "助手未配置密钥（DEEPSEEK_API_KEY）。", "changed": None}

        async with self._lock:          # 串行，避免并发改对话历史
            state = self.lexicon.snapshot()
            system = SYSTEM.format(
                hotword_state=(
                    f"共 {state['total']} 个；用户自定义 {len(state['custom'])} 个"
                    + (f"（{'、'.join(state['custom'][:6])}）" if state["custom"] else "")
                )
            )
            messages = [{"role": "system", "content": system}, *self.history[-self.MAX_TURNS * 2:]]
            messages.append({"role": "user", "content": message})

            changed = None
            try:
                client = self._get_client()
                resp = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=config.CHAT_MODEL,
                        messages=messages,
                        tools=TOOLS,
                        temperature=0.3,
                        max_tokens=500,
                    ),
                    timeout=config.CHAT_TIMEOUT,
                )
                msg = resp.choices[0].message

                if msg.tool_calls:
                    # 把工具的调用结果回灌给模型，让它用一句话确认
                    messages.append({
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [
                            {"id": tc.id, "type": "function",
                             "function": {"name": tc.function.name,
                                          "arguments": tc.function.arguments}}
                            for tc in msg.tool_calls
                        ],
                    })
                    for tc in msg.tool_calls:
                        changed = self._run_tool(tc)
                        messages.append({
                            "role": "tool", "tool_call_id": tc.id,
                            "content": json.dumps(changed, ensure_ascii=False),
                        })
                    second = await asyncio.wait_for(
                        client.chat.completions.create(
                            model=config.CHAT_MODEL,
                            messages=messages,
                            temperature=0.3,
                            max_tokens=200,
                        ),
                        timeout=config.CHAT_TIMEOUT,
                    )
                    reply = (second.choices[0].message.content or "").strip()
                else:
                    reply = (msg.content or "").strip()

                self.history.append({"role": "user", "content": message})
                self.history.append({"role": "assistant", "content": reply})
                return {"reply": reply, "changed": changed}

            except asyncio.TimeoutError:
                log.warning("助手响应超时")
                return {"reply": "助手响应超时，请再问一次。", "changed": changed}
            except Exception as exc:
                log.warning("助手调用失败：%s", exc)
                return {"reply": f"助手暂时不可用（{type(exc).__name__}）。", "changed": changed}

    def _run_tool(self, tool_call) -> dict:
        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except ValueError:
            return {"error": "参数解析失败"}
        added = self.lexicon.add(args.get("add") or [])
        removed = self.lexicon.remove(args.get("remove") or [])
        return {
            "added": added,
            "removed": removed,
            "hotwords": self.lexicon.hotwords(),
            "note": "热词已保存，下一次点「开始」时生效",
        }
