"""Answer analyzer: mention detection, placement, competitors, scoring."""

from app.ai_checks import analyze_answer


def test_mentioned_by_name_early_scores_high():
    answer = ("Bright Smile Dental is the top-rated clinic in DHA. "
              "It offers painless root canals. Alternatives include Pearl Dental Care.")
    r = analyze_answer(answer, "Bright Smile Dental", "https://brightsmile.example.com")
    assert r["mentioned"] is True
    assert r["placement"] is not None and r["placement"] < 0.33
    assert r["score"] >= 80  # 60 base + 20 early placement
    assert "Pearl Dental Care" in r["competitors"]


def test_mentioned_by_domain_gets_citation_bonus():
    answer = ("Consider brightsmile.example.com for family dentistry. "
              "Pearl Dental Care is another option.")
    r = analyze_answer(answer, "Bright Smile Dental", "https://brightsmile.example.com")
    assert r["mentioned"] is True
    assert r["score"] == 100  # 60 + 20 early + 20 domain cited


def test_not_mentioned_scores_zero():
    answer = ("Top picks: Pearl Dental Care and CitySmile Studio. "
              "Both have great reviews for whitening.")
    r = analyze_answer(answer, "Bright Smile Dental", "https://brightsmile.example.com")
    assert r["mentioned"] is False
    assert r["score"] == 0
    assert r["placement"] is None
    assert "Pearl Dental Care" in r["competitors"]


def test_late_mention_scores_less_than_early():
    early = "Bright Smile Dental is great. " + "filler " * 100
    late = "filler " * 100 + "Bright Smile Dental is great."
    re_ = analyze_answer(early, "Bright Smile Dental", "https://x.example.com")
    rl = analyze_answer(late, "Bright Smile Dental", "https://x.example.com")
    assert re_["mentioned"] and rl["mentioned"]
    assert re_["score"] > rl["score"]


def test_competitor_extraction_ignores_own_name_and_generic_words():
    answer = ("Bright Smile Dental offers the best services. The top clinic "
              "for implants is Pearl Dental Care in Karachi.")
    r = analyze_answer(answer, "Bright Smile Dental", "https://brightsmile.example.com")
    assert "Bright Smile Dental" not in r["competitors"]
    assert "Pearl Dental Care" in r["competitors"]
    # generic capitalised words should not be reported as competitors
    for c in r["competitors"]:
        assert c.lower() not in {"the top", "best services"}


def test_empty_answer_is_safe():
    r = analyze_answer("", "Bright Smile Dental", "https://brightsmile.example.com")
    assert r == {"mentioned": False, "placement": None,
                 "competitors": [], "score": 0}
