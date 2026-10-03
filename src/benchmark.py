from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_advanced import AdvancedAgent
from agent_baseline import BaselineAgent
from config import LabConfig, load_config
from tabulate import tabulate


@dataclass
class BenchmarkRow:
    agent_name: str
    agent_tokens_only: int
    prompt_tokens_processed: int
    recall_score: float
    response_quality: float
    memory_growth_bytes: int
    compactions: int


def load_conversations(path: Path) -> list[dict[str, Any]]:
    """Read JSON conversations from disk."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def recall_points(answer: str, expected: list[str]) -> float:
    """Return ratio (0.0 to 1.0) of how many expected facts appear in the answer."""
    if not expected:
        return 1.0
    ans_lower = answer.lower()
    matches = sum(1 for item in expected if item.lower() in ans_lower)
    return matches / len(expected)


def heuristic_quality(answer: str, expected: list[str]) -> float:
    """Compute lightweight quality score for offline benchmark (0.0 to 1.0 scale)."""
    if not answer or not answer.strip():
        return 0.0

    # 1. Base points for relevance and non-empty coherent reply
    base = 0.5

    # 2. Fact inclusion points
    recall = recall_points(answer, expected)
    fact_score = recall * 0.4

    # 3. Formatting quality (structured bullets, concise sentences)
    format_score = 0.1 if ("-" in answer or "\n" in answer or len(answer.split()) > 8) else 0.05

    return min(1.0, base + fact_score + format_score)


def run_agent_benchmark(
    agent_name: str,
    agent: Any,
    conversations: list[dict[str, Any]],
    config: LabConfig,
) -> BenchmarkRow:
    """Evaluate one agent over multiple conversations and recall questions."""
    total_agent_tokens = 0
    total_prompt_tokens = 0
    recall_scores: list[float] = []
    quality_scores: list[float] = []
    total_compactions = 0

    initial_sizes: dict[str, int] = {}
    final_sizes: dict[str, int] = {}

    for conv in conversations:
        conv_id = conv.get("id", "c1")
        user_id = conv.get("user_id", "user")
        thread_id = f"bench-{agent_name}-{conv_id}"

        if hasattr(agent, "memory_file_size") and user_id not in initial_sizes:
            initial_sizes[user_id] = agent.memory_file_size(user_id)

        # 1. Feed turns within the main thread
        for turn in conv.get("turns", []):
            res = agent.reply(user_id, thread_id, turn)
            total_agent_tokens += res.get("token_usage", 0)

        # Record prompt tokens and compactions from the main thread
        total_prompt_tokens += agent.prompt_token_usage(thread_id)
        total_compactions += agent.compaction_count(thread_id)

        # 2. Ask recall questions in a FRESH thread to evaluate cross-session recall
        for q_idx, rq in enumerate(conv.get("recall_questions", [])):
            recall_thread = f"bench-recall-{agent_name}-{conv_id}-{q_idx}"
            question = rq.get("question", "")
            expected = rq.get("expected_contains", [])

            res = agent.reply(user_id, recall_thread, question)
            ans = str(res.get("reply", ""))
            total_agent_tokens += res.get("token_usage", 0)
            total_prompt_tokens += agent.prompt_token_usage(recall_thread)

            score = recall_points(ans, expected)
            recall_scores.append(score)
            quality_scores.append(heuristic_quality(ans, expected))

        if hasattr(agent, "memory_file_size"):
            final_sizes[user_id] = agent.memory_file_size(user_id)

    # Calculate memory growth
    mem_growth = sum(final_sizes.values()) - sum(initial_sizes.values()) if final_sizes else 0
    avg_recall = sum(recall_scores) / max(len(recall_scores), 1)
    avg_quality = sum(quality_scores) / max(len(quality_scores), 1)

    return BenchmarkRow(
        agent_name=agent_name,
        agent_tokens_only=total_agent_tokens,
        prompt_tokens_processed=total_prompt_tokens,
        recall_score=avg_recall,
        response_quality=avg_quality,
        memory_growth_bytes=max(0, mem_growth),
        compactions=total_compactions,
    )


def format_rows(rows: list[BenchmarkRow]) -> str:
    """Format benchmark rows as an ASCII table using tabulate."""
    headers = [
        "Agent",
        "Agent tokens only",
        "Prompt tokens processed",
        "Cross-session recall",
        "Response quality",
        "Memory growth (bytes)",
        "Compactions",
    ]
    table_data = []
    for r in rows:
        table_data.append([
            r.agent_name,
            f"{r.agent_tokens_only:,}",
            f"{r.prompt_tokens_processed:,}",
            f"{r.recall_score * 100:.1f}%",
            f"{r.response_quality * 10:.2f} / 10",
            f"{r.memory_growth_bytes:,} B",
            r.compactions,
        ])
    return tabulate(table_data, headers=headers, tablefmt="grid")


def main() -> None:
    """Run both Standard Benchmark and Long-Context Stress Benchmark."""
    base_dir = Path(__file__).resolve().parent.parent
    config = load_config(base_dir)

    # Clean previous state to start with pristine memory
    state_profiles = config.state_dir / "profiles"
    if state_profiles.exists():
        shutil.rmtree(state_profiles, ignore_errors=True)
    state_profiles.mkdir(parents=True, exist_ok=True)

    # 1. Standard Benchmark
    std_data_path = config.data_dir / "conversations.json"
    std_convs = load_conversations(std_data_path)

    baseline_std = BaselineAgent(config, force_offline=True)
    advanced_std = AdvancedAgent(config, force_offline=True)

    row_base_std = run_agent_benchmark("Baseline", baseline_std, std_convs, config)
    row_adv_std = run_agent_benchmark("Advanced", advanced_std, std_convs, config)

    print("\n=======================================================")
    print(" 📊 SUITE 1: STANDARD BENCHMARK (10 CONVERSATIONS)")
    print("=======================================================")
    print(format_rows([row_base_std, row_adv_std]))

    # 2. Long-Context Stress Benchmark
    stress_data_path = config.data_dir / "advanced_long_context.json"
    stress_convs = load_conversations(stress_data_path)

    baseline_stress = BaselineAgent(config, force_offline=True)
    advanced_stress = AdvancedAgent(config, force_offline=True)

    row_base_stress = run_agent_benchmark("Baseline", baseline_stress, stress_convs, config)
    row_adv_stress = run_agent_benchmark("Advanced", advanced_stress, stress_convs, config)

    print("\n=======================================================")
    print(" 🚀 SUITE 2: LONG-CONTEXT STRESS BENCHMARK (16 TURNS)")
    print("=======================================================")
    print(format_rows([row_base_stress, row_adv_stress]))
    print("\n")


if __name__ == "__main__":
    main()
