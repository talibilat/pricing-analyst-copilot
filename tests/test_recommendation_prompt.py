from pricing_copilot.recommendation.synthesizer import SYSTEM_PROMPT


def test_synthesizer_prompt_prohibits_unsupported_cross_segment_comparisons() -> None:
    assert "Do not compare renewal and new-business performance" in SYSTEM_PROMPT
