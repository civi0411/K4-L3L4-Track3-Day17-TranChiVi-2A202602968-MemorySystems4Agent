from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from config import LabConfig, load_config
from memory_store import estimate_tokens
from model_provider import build_chat_model


@dataclass
class SessionState:
    messages: list[dict[str, str]] = field(default_factory=list)
    token_usage: int = 0
    prompt_tokens_processed: int = 0


class BaselineAgent:
    """Agent A: Baseline Agent.

    Characteristics:
    - Thread-local / within-session memory only
    - No persistent User.md profile
    - Forgets all long-term facts when switched to a new thread
    - Accumulates full uncompressed context in the same thread
    """

    def __init__(self, config: LabConfig | None = None, force_offline: bool = True) -> None:
        self.config = config or load_config()
        self.force_offline = force_offline
        self.sessions: dict[str, SessionState] = {}
        self.langchain_agent = None

        if not self.force_offline:
            self.langchain_agent = self._maybe_build_langchain_agent()

    def _get_session(self, thread_id: str) -> SessionState:
        if thread_id not in self.sessions:
            self.sessions[thread_id] = SessionState()
        return self.sessions[thread_id]

    def reply(self, user_id: str, thread_id: str, message: str) -> dict[str, Any]:
        """Route to offline path or live LangChain agent."""
        if self.force_offline or self.langchain_agent is None:
            return self._reply_offline(thread_id, message)

        # Optional live path if agent was initialized
        try:
            res = self.langchain_agent.invoke(
                {"input": message},
                {"configurable": {"thread_id": thread_id}},
            )
            reply_text = str(res.get("output", res))
            session = self._get_session(thread_id)
            prompt_load = sum(estimate_tokens(m["content"]) for m in session.messages) + estimate_tokens(message)
            out_tokens = estimate_tokens(reply_text)
            session.prompt_tokens_processed += prompt_load
            session.token_usage += out_tokens
            session.messages.append({"role": "user", "content": message})
            session.messages.append({"role": "assistant", "content": reply_text})
            return {"reply": reply_text, "token_usage": out_tokens, "prompt_tokens": prompt_load}
        except Exception:
            return self._reply_offline(thread_id, message)

    def token_usage(self, thread_id: str) -> int:
        """Return cumulative agent output token count for a thread."""
        return self._get_session(thread_id).token_usage

    def prompt_token_usage(self, thread_id: str) -> int:
        """Estimate cumulative prompt context tokens processed across all turns."""
        return self._get_session(thread_id).prompt_tokens_processed

    def compaction_count(self, thread_id: str) -> int:
        """Baseline has no compact memory."""
        return 0

    def _reply_offline(self, thread_id: str, message: str) -> dict[str, Any]:
        """Deterministic baseline response logic."""
        session = self._get_session(thread_id)

        # Baseline must carry all previous messages in this thread into prompt context
        prompt_load = sum(estimate_tokens(m["content"]) for m in session.messages) + estimate_tokens(message)
        session.prompt_tokens_processed += prompt_load

        # Record incoming user message
        session.messages.append({"role": "user", "content": message})

        # Generate response based strictly on within-thread history
        lower = message.lower()
        is_recall_query = any(k in lower for k in ["tên gì", "nhắc lại", "đồ uống", "ở đâu", "nghề gì", "style"])

        # Check if the facts were stated in THIS thread
        thread_text = " ".join(m["content"] for m in session.messages[:-1]).lower()

        if is_recall_query and not thread_text:
            # Fresh thread with no prior context -> baseline cannot know
            reply_text = "Xin chào! Vì đây là phiên làm việc mới và tôi chưa có dữ liệu trước đó, tôi không biết thông tin về tên hoặc sở thích của bạn."
        elif is_recall_query:
            # Look up within this thread only
            found_facts: list[str] = []
            m_name = re.search(r"tên là\s+([A-Za-z0-9_À-ỹ]+)", thread_text)
            if m_name:
                found_facts.append(f"Tên: {m_name.group(1)}")
            if "cà phê sữa đá" in thread_text:
                found_facts.append("Đồ uống: cà phê sữa đá")
            if "đà nẵng" in thread_text:
                found_facts.append("Nơi ở: Đà Nẵng")
            if "huế" in thread_text:
                found_facts.append("Nơi ở: Huế")

            if found_facts:
                reply_text = "Dựa vào thông tin bạn vừa chia sẻ trong cuộc trò chuyện này: " + ", ".join(found_facts) + "."
            else:
                reply_text = "Tôi chỉ nhớ những gì bạn trao đổi gần đây trong phiên này."
        else:
            reply_text = "Tôi đã ghi nhận thông tin của bạn trong phiên trò chuyện này."

        out_tokens = estimate_tokens(reply_text)
        session.token_usage += out_tokens
        session.messages.append({"role": "assistant", "content": reply_text})

        return {
            "reply": reply_text,
            "token_usage": out_tokens,
            "prompt_tokens": prompt_load,
        }

    def _maybe_build_langchain_agent(self):
        """Optional wire-up for live LangChain model."""
        try:
            return build_chat_model(self.config.model)
        except Exception:
            return None
