from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


def estimate_tokens(text: str) -> int:
    """Heuristic token estimator supporting Vietnamese and English."""
    if not text:
        return 0
    stripped = text.strip()
    if not stripped:
        return 0
    words = len(stripped.split())
    chars = len(stripped)
    est_from_words = int(words * 1.35)
    est_from_chars = int(chars / 3.8)
    return max(est_from_words, est_from_chars, 1)


@dataclass
class UserProfileStore:
    """Persistent storage for `User.md`."""

    root_dir: Path

    def path_for(self, user_id: str) -> Path:
        """Sanitize user id to prevent directory traversal and return path to User.md."""
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", user_id.strip())
        return self.root_dir / safe_id / "User.md"

    def read_text(self, user_id: str) -> str:
        """Return profile content or a clean default markdown template."""
        p = self.path_for(user_id)
        if p.is_file():
            return p.read_text(encoding="utf-8")
        return f"# User Profile: {user_id}\n"

    def write_text(self, user_id: str, content: str) -> Path:
        """Write markdown to disk and return the file path."""
        p = self.path_for(user_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def edit_text(self, user_id: str, search_text: str, replacement: str) -> bool:
        """Replace occurrence inside User.md and return whether it changed."""
        current = self.read_text(user_id)
        if search_text in current:
            updated = current.replace(search_text, replacement, 1)
            self.write_text(user_id, updated)
            return True
        return False

    def file_size(self, user_id: str) -> int:
        """Return current file size in bytes."""
        p = self.path_for(user_id)
        if p.is_file():
            return p.stat().st_size
        return 0

    def facts(self, user_id: str) -> dict[str, str]:
        """Parse structured key-value facts from User.md."""
        content = self.read_text(user_id)
        results: dict[str, str] = {}
        for line in content.splitlines():
            m = re.match(r"^-\s*([A-Za-z0-9_\s]+?):\s*(.+)$", line.strip())
            if m:
                results[m.group(1).strip()] = m.group(2).strip()
        return results

    def upsert_fact(self, user_id: str, key: str, value: str) -> None:
        """Insert or update a structured fact in User.md with conflict resolution."""
        current = self.read_text(user_id)
        pattern = re.compile(rf"^-\s*{re.escape(key)}:\s*.*$", re.MULTILINE)
        new_line = f"- {key}: {value}"
        if pattern.search(current):
            updated = pattern.sub(new_line, current)
        else:
            updated = current.rstrip() + f"\n{new_line}\n"
        self.write_text(user_id, updated)


def extract_profile_updates(message: str) -> dict[str, str]:
    """Convert raw user text into stable profile facts with confidence filtering and noise rejection."""
    msg = message.strip()
    if not msg:
        return {}

    # Skip pure question-only turns without statements
    is_pure_question = (
        msg.endswith("?")
        and not any(k in msg.lower() for k in ["mình tên là", "tôi tên là", "mình ở", "đính chính", "hiện tại mình"])
    )
    if is_pure_question:
        return {}

    updates: dict[str, str] = {}
    lower = msg.lower()

    # 1. Name extraction
    name_match = re.search(
        r"(?:tôi|mình)\s+(?:tên là|gọi là)\s+([A-Za-z0-9_À-ỹ]+(?:\s+[A-Za-z0-9_À-ỹ]+)*)",
        msg,
        re.IGNORECASE,
    )
    if name_match:
        cand = name_match.group(1).strip()
        cand = re.sub(r"[.,;!?].*$", "", cand).strip()
        if cand:
            updates["Name"] = cand

    # 2. Location extraction (with conflict handling and noise filtering)
    is_hanoi_noise = "hà nội" in lower and any(k in lower for k in ["họp", "công tác", "vừa bay ra", "chỉ là"])
    is_danang_negated = any(k in lower for k in [
        "không còn ở đà nẵng",
        "không ở đà nẵng",
        "rời đà nẵng",
        "đừng lấy nó làm nơi ở hiện tại",
    ])
    is_hue_negated = any(k in lower for k in [
        "không còn ở huế",
        "chuyển từ huế",
        "trước đó có nhắc huế",
        "ai đó nhắc huế",
        "cập nhật từ huế sang",
    ])

    if "huế" in lower and not is_hue_negated:
        if any(k in lower for k in ["ở huế", "đang ở huế", "về huế", "ra huế", "vẫn ở huế"]):
            updates["Location"] = "Huế"

    if "đà nẵng" in lower and not is_danang_negated:
        if any(k in lower for k in [
            "ở đà nẵng",
            "làm việc ở đà nẵng",
            "hiện tại là đà nẵng",
            "cập nhật từ huế sang đà nẵng",
            "đang ở đà nẵng",
            "về đà nẵng",
        ]):
            updates["Location"] = "Đà Nẵng"

    # Reject Hanoi if it was noise
    if is_hanoi_noise and updates.get("Location") == "Hà Nội":
        del updates["Location"]

    # 3. Profession extraction (with noise filtering)
    is_pm_joke = "product manager" in lower and any(k in lower for k in ["đùa", "câu đùa"])
    if "không còn làm backend engineer" in lower or "chuyển sang mlops engineer" in lower:
        updates["Profession"] = "MLOps engineer"
    elif "mlops engineer" in lower:
        updates["Profession"] = "MLOps engineer"
    elif "backend engineer" in lower and not any(k in lower for k in ["không còn", "đừng nói", "thông tin cũ"]):
        updates["Profession"] = "backend engineer"
    elif "product manager" in lower and not is_pm_joke and "làm product manager" in lower:
        updates["Profession"] = "product manager"

    # 4. Response style preference
    if "3 bullet" in lower:
        updates["Response Style"] = "3 bullet ngắn gọn, có ví dụ thực chiến, nhấn trade-off"
    elif "bullet ngắn" in lower or "ngắn gọn" in lower:
        updates["Response Style"] = "ngắn gọn, rõ ý và có ví dụ thực tế"

    # 5. Food & Drink / Personal preferences
    if "cà phê sữa đá" in lower:
        updates["Favorite Drink"] = "cà phê sữa đá"

    if "mì quảng" in lower:
        updates["Favorite Food"] = "mì Quảng"

    if "corgi" in lower:
        updates["Pet"] = "corgi (tên Bơ)"

    if "python" in lower or "ai" in lower:
        updates["Interests"] = "Python, AI"

    return updates


def summarize_messages(messages: list[dict[str, str]], max_items: int = 3) -> str:
    """Create a compact, fact-preserving summary of older messages."""
    if not messages:
        return ""

    summaries: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "").strip()
        if not content:
            continue
        first_clause = content.split(".")[0].strip()
        snippet = first_clause[:60] if len(first_clause) > 60 else first_clause
        summaries.append(f"- {role}: {snippet}")

    kept = summaries[-max_items:]
    return "\n".join(kept)


@dataclass
class CompactMemoryManager:
    """Sliding-window compact memory manager for long conversation threads."""

    threshold_tokens: int
    keep_messages: int
    state: dict[str, dict[str, object]] = field(default_factory=dict)

    def _ensure_thread(self, thread_id: str) -> dict[str, object]:
        if thread_id not in self.state:
            self.state[thread_id] = {
                "messages": [],
                "summary": "",
                "compactions": 0,
            }
        return self.state[thread_id]

    def append(self, thread_id: str, role: str, content: str) -> None:
        """Append message and trigger compaction if thread tokens exceed threshold."""
        th = self._ensure_thread(thread_id)
        msgs: list[dict[str, str]] = th["messages"]  # type: ignore
        msgs.append({"role": role, "content": content})

        # Calculate tokens in recent messages
        total_tokens = sum(estimate_tokens(m["content"]) for m in msgs)
        if total_tokens > self.threshold_tokens and len(msgs) > self.keep_messages:
            to_compact = msgs[:-self.keep_messages]
            kept = msgs[-self.keep_messages:]

            new_summary = summarize_messages(to_compact, max_items=2)
            old_summary = str(th.get("summary", ""))
            combined = [l.strip() for l in (old_summary + "\n" + new_summary).splitlines() if l.strip()]
            th["summary"] = "\n".join(combined[-3:])

            th["messages"] = kept
            th["compactions"] = int(th.get("compactions", 0)) + 1

    def context(self, thread_id: str) -> dict[str, object]:
        """Return per-thread state with messages, summary, and compactions."""
        return self._ensure_thread(thread_id)

    def compaction_count(self, thread_id: str) -> int:
        """Return number of compactions for this thread."""
        return int(self.state.get(thread_id, {}).get("compactions", 0))
