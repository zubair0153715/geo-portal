"""Prompt-pack builder: neutral prompts, one per phrase per provider."""

from app.ai_checks import build_prompt_pack


PHRASES = ["best dental clinic in Karachi", "painless root canal near me"]


def test_pack_has_all_providers_and_phrases():
    pack = build_prompt_pack("Bright Smile Dental", "https://brightsmile.example.com", PHRASES)
    assert set(pack) == {"chatgpt", "perplexity", "gemini"}
    for provider_prompts in pack.values():
        assert len(provider_prompts) == 2


def test_prompts_are_neutral_no_business_name():
    pack = build_prompt_pack("Bright Smile Dental", "https://brightsmile.example.com", PHRASES)
    for provider_prompts in pack.values():
        for prompt in provider_prompts:
            assert "Bright Smile Dental" not in prompt
            assert "brightsmile.example.com" not in prompt


def test_prompts_contain_the_customer_phrase():
    pack = build_prompt_pack("Bright Smile Dental", "https://x.example.com", PHRASES)
    for provider_prompts in pack.values():
        joined = " ".join(provider_prompts)
        for phrase in PHRASES:
            assert phrase in joined


def test_blank_phrases_skipped():
    pack = build_prompt_pack("Biz", "https://x.example.com", ["  ", "real phrase", ""])
    for provider_prompts in pack.values():
        assert len(provider_prompts) == 1
