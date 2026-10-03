from __future__ import annotations

from pathlib import Path

from agent_advanced import AdvancedAgent
from agent_baseline import BaselineAgent
from config import LabConfig
from memory_store import CompactMemoryManager, UserProfileStore
from model_provider import ProviderConfig


def make_config(tmp_path: Path) -> LabConfig:
    """Build an isolated configuration for unit tests."""
    data_dir = Path(__file__).resolve().parent.parent / "data"
    state_dir = tmp_path / "state"
    (state_dir / "profiles").mkdir(parents=True, exist_ok=True)

    dummy_model = ProviderConfig(
        provider="openai",
        model_name="gpt-4o-mini",
        temperature=0.0,
    )

    return LabConfig(
        base_dir=tmp_path,
        data_dir=data_dir,
        state_dir=state_dir,
        compact_threshold_tokens=150,  # low threshold so compaction triggers easily in tests
        compact_keep_messages=2,
        model=dummy_model,
        judge_model=dummy_model,
    )


def test_user_markdown_read_write_edit(tmp_path: Path) -> None:
    """Verify User.md can be created, updated, and edited with conflict resolution."""
    profiles_dir = tmp_path / "profiles"
    store = UserProfileStore(profiles_dir)

    # 1. Read non-existent profile returns default template
    initial = store.read_text("test_user")
    assert "# User Profile: test_user" in initial
    assert store.file_size("test_user") == 0

    # 2. Write initial markdown
    written_path = store.write_text("test_user", "# User Profile\n- Location: Đà Nẵng\n")
    assert written_path.exists()
    assert store.file_size("test_user") > 0

    # 3. Edit text
    changed = store.edit_text("test_user", "Đà Nẵng", "Huế")
    assert changed is True
    assert "Huế" in store.read_text("test_user")
    assert "Đà Nẵng" not in store.read_text("test_user")

    # 4. Upsert fact
    store.upsert_fact("test_user", "Location", "Hà Nội")
    facts = store.facts("test_user")
    assert facts.get("Location") == "Hà Nội"


def test_compact_trigger(tmp_path: Path) -> None:
    """Verify long threads trigger compaction and summarize older context."""
    manager = CompactMemoryManager(threshold_tokens=60, keep_messages=2)
    thread_id = "test-thread"

    # Add messages that exceed 60 tokens
    manager.append(thread_id, "user", "Tin đầu tiên rất dài về NASA và Artemis III cùng nhiều dữ kiện kỹ thuật chi tiết.")
    manager.append(thread_id, "assistant", "Đã nhận được thông tin về chương trình NASA Artemis III.")
    manager.append(thread_id, "user", "Tin thứ hai về X-59 và tốc độ siêu thanh Mach 1.1 ở độ cao 29500 feet.")
    manager.append(thread_id, "assistant", "Đã ghi nhận dữ liệu về máy bay X-59.")

    ctx = manager.context(thread_id)
    assert manager.compaction_count(thread_id) >= 1
    assert len(ctx["messages"]) <= 2  # type: ignore
    assert len(str(ctx["summary"])) > 0


def test_cross_session_recall(tmp_path: Path) -> None:
    """Verify advanced agent remembers across sessions while baseline does not."""
    cfg = make_config(tmp_path)
    baseline = BaselineAgent(cfg, force_offline=True)
    advanced = AdvancedAgent(cfg, force_offline=True)

    user_id = "test_dung"
    session_1 = "thread-intro"
    session_2 = "thread-recall"

    # Session 1: User provides name and drink
    intro_msg = "Chào bạn, mình tên là DũngCT và đồ uống yêu thích của mình là cà phê sữa đá."
    baseline.reply(user_id, session_1, intro_msg)
    advanced.reply(user_id, session_1, intro_msg)

    # Session 2 (New thread): Recall question
    recall_q = "Mình tên gì và đồ uống yêu thích là gì?"
    base_reply = baseline.reply(user_id, session_2, recall_q)["reply"]
    adv_reply = advanced.reply(user_id, session_2, recall_q)["reply"]

    # Baseline forgets across new thread
    assert "DũngCT" not in base_reply
    assert "cà phê sữa đá" not in base_reply

    # Advanced recalls across new thread
    assert "DũngCT" in adv_reply
    assert "cà phê sữa đá" in adv_reply


def test_compact_reduces_prompt_load_on_long_thread(tmp_path: Path) -> None:
    """Compare prompt load of baseline vs advanced on a long thread."""
    cfg = make_config(tmp_path)
    baseline = BaselineAgent(cfg, force_offline=True)
    advanced = AdvancedAgent(cfg, force_offline=True)

    thread_id = "stress-load-test"
    user_id = "stress_user"

    long_paragraph = (
        "Đây là một lượt trao đổi rất dài với rất nhiều chi tiết kỹ thuật về tối ưu hóa hệ thống bộ nhớ, "
        "quản lý ngữ cảnh, giảm thiểu chi phí prompt token và duy trì độ chính xác cao trong bài test benchmark."
    )

    # Run 12 turns on the same thread
    for i in range(12):
        turn_text = f"Lượt {i}: {long_paragraph}"
        baseline.reply(user_id, thread_id, turn_text)
        advanced.reply(user_id, thread_id, turn_text)

    # Prompt tokens processed by Baseline should be significantly higher due to O(N^2) context accumulation
    base_prompt_tokens = baseline.prompt_token_usage(thread_id)
    adv_prompt_tokens = advanced.prompt_token_usage(thread_id)

    assert adv_prompt_tokens < base_prompt_tokens
    assert advanced.compaction_count(thread_id) >= 1


def test_conflict_and_noise_handling(tmp_path: Path) -> None:
    """Bonus test: Verify conflict resolution (location update) and noise rejection (Hanoi meeting, PM joke)."""
    cfg = make_config(tmp_path)
    agent = AdvancedAgent(cfg, force_offline=True)
    user_id = "dungct_bonus"
    th = "th-bonus"

    # 1. State initial location and job
    agent.reply(user_id, th, "Chào bạn, mình tên là DũngCT, ở Đà Nẵng và làm MLOps engineer.")
    facts1 = agent.profile_store.facts(user_id)
    assert facts1.get("Location") == "Đà Nẵng"
    assert facts1.get("Profession") == "MLOps engineer"

    # 2. Add noise: meeting in Hanoi & PM joke
    agent.reply(user_id, th, "Hôm qua mình ra Hà Nội họp đối tác 2 ngày. Có lúc đùa hay chuyển sang làm product manager.")
    facts2 = agent.profile_store.facts(user_id)
    assert facts2.get("Location") == "Đà Nẵng"  # Not overwritten by Hanoi meeting
    assert facts2.get("Profession") == "MLOps engineer"  # Not overwritten by PM joke

    # 3. Valid update / conflict resolution: moved to Hue
    agent.reply(user_id, th, "À mình đính chính một chút, giờ mình đang ở Huế chứ không còn ở Đà Nẵng nữa.")
    facts3 = agent.profile_store.facts(user_id)
    assert facts3.get("Location") == "Huế"
    assert "Đà Nẵng" not in facts3.get("Location", "")
