"""AI visibility checks: ask AI providers a neutral customer question, then
analyse whether they mention the client's business.

Measurement honesty: the prompt sent to the provider NEVER names the client's
business — we measure what the AI volunteers on its own, like a real customer
would see. `build_prompt_pack` produces the same neutral prompts for the
manual copy-paste path.

All API keys come from the encrypted vault at call time. Nothing is hardcoded.
"""

import re
import urllib.parse

import httpx

# ---------------------------------------------------------------- prompt ----
NEUTRAL_PROMPT = (
    "Answer factually and concisely. A customer asks: '{phrase}'. "
    "List the best options you know, each with a one-line description. "
    "Do not ask follow-up questions."
)

# ------------------------------------------------------- provider calls ----
def run_openai(api_key: str, phrase: str, model: str = "gpt-4o-mini") -> str:
    with httpx.Client(timeout=90) as client:
        resp = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user",
                              "content": NEUTRAL_PROMPT.format(phrase=phrase)}],
                "temperature": 0.2,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def run_perplexity(api_key: str, phrase: str, model: str = "sonar") -> str:
    with httpx.Client(timeout=90) as client:
        resp = client.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user",
                              "content": NEUTRAL_PROMPT.format(phrase=phrase)}],
                "temperature": 0.2,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def run_gemini(api_key: str, phrase: str, model: str = "gemini-2.0-flash") -> str:
    # NOTE: Gemini AI Studio has a free tier (rate-limited) — good for trials.
    # Paid usage is billed per token via the same key.
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
           f":generateContent?key={api_key}")
    with httpx.Client(timeout=90) as client:
        resp = client.post(
            url,
            json={"contents": [{"parts": [
                {"text": NEUTRAL_PROMPT.format(phrase=phrase)}]}]},
        )
        resp.raise_for_status()
        parts = resp.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)


PROVIDERS = {
    "openai": run_openai,
    "perplexity": run_perplexity,
    "gemini": run_gemini,
}

AI_PROVIDER_LABELS = {
    "openai": "ChatGPT (OpenAI)",
    "perplexity": "Perplexity",
    "gemini": "Gemini (Google)",
}


def run_check(provider: str, api_key: str, phrase: str) -> str:
    """Run one visibility check. Raises KeyError on unknown provider."""
    return PROVIDERS[provider](api_key, phrase)


# ------------------------------------------------------------- analysis ----
# Words that can never *start/continue* a business-name run (pure function words).
FUNCTION_WORDS = {
    "the", "a", "an", "and", "or", "for", "of", "in", "on", "at", "to", "with",
    "from", "by", "as", "it", "its", "they", "them", "he", "she", "we", "you",
    "i", "me", "my", "if", "then", "than", "so", "such", "some", "any", "all",
    "each", "both", "few", "other", "another", "into", "over", "under", "again",
    "once", "when", "where", "which", "who", "whom", "what", "how", "why",
    "is", "are", "was", "were", "be", "been", "has", "have", "had", "will",
    "would", "can", "could", "should", "may", "might", "must", "do", "does",
    "did", "not", "no", "yes", "via", "per", "vs", "etc", "one", "two",
    "three", "first", "second", "third", "more", "most", "many", "much",
    "very", "just", "also", "well", "get", "find", "finding", "found", "look",
    "looking", "need", "needs", "want", "make", "take", "use", "using", "used",
    "based", "located", "offers", "offer", "offering", "provides", "providing",
    "provide", "known", "option", "options", "choice", "choices", "list",
    "including", "include",
}

# Generic words: allowed *inside* a name run ("Pearl Dental Care") but a
# candidate made ONLY of these ("The Top Clinic") is not a business name.
GENERIC_WORDS = FUNCTION_WORDS | {
    "best", "top", "new", "leading", "trusted", "affordable", "book", "visit",
    "call", "now", "today", "here", "your", "our", "their", "this", "that",
    "these", "those", "dental", "clinic", "clinics", "center", "centre",
    "hospital", "hospitals", "care", "health", "service", "services",
}


def domain_of(website: str) -> str:
    netloc = urllib.parse.urlparse(
        website if "://" in website else "https://" + website).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def _find_mention(answer: str, business_name: str, domain: str):
    """Return (mentioned: bool, position_fraction: float|None)."""
    low = answer.lower()
    name_hit = business_name.strip().lower() in low if business_name.strip() else False
    domain_hit = bool(domain) and domain in low
    mentioned = name_hit or domain_hit
    if not mentioned:
        return False, None
    # earliest hit position as a fraction of answer length (0 = very top)
    positions = []
    if name_hit:
        positions.append(low.index(business_name.strip().lower()))
    if domain_hit:
        positions.append(low.index(domain))
    frac = min(positions) / max(len(answer), 1)
    return True, frac


def _extract_competitors(answer: str, business_name: str, domain: str,
                         max_names: int = 8) -> list:
    """Heuristic: Title-Case 2–4 word runs containing at least one distinctive
    (non-generic) word, e.g. "Pearl Dental Care" (distinctive: "Pearl").

    This is intentionally simple and documented as a heuristic — it finds
    candidate rival names for the client to review, not ground truth.
    """
    own = business_name.strip().lower()
    candidates = []
    words = re.findall(r"[A-Za-z][A-Za-z'&-]*", answer)
    i = 0
    while i < len(words):
        w = words[i]
        if w[0].isupper() and w.lower() not in FUNCTION_WORDS:
            run = [w]
            j = i + 1
            while (j < len(words) and len(run) < 4
                   and words[j][0].isupper()
                   and words[j].lower() not in FUNCTION_WORDS):
                run.append(words[j])
                j += 1
            if 2 <= len(run) <= 4:
                phrase = " ".join(run)
                low = phrase.lower()
                distinctive = any(t.lower() not in GENERIC_WORDS for t in run)
                is_own = (low == own or (own and (own in low or low in own)))
                if (distinctive and not is_own
                        and not (domain and domain in low)
                        and phrase not in candidates):
                    candidates.append(phrase)
            i = j
        else:
            i += 1
    return candidates[:max_names]


def _score(mentioned: bool, position_frac, domain_cited: bool) -> int:
    if not mentioned:
        return 0
    score = 60  # mentioned at all
    if position_frac is not None:
        if position_frac < 0.33:
            score += 20   # mentioned near the top
        elif position_frac < 0.66:
            score += 10
    if domain_cited:
        score += 20       # website actually cited/linked
    return min(score, 100)


def analyze_answer(answer: str, business_name: str, website: str) -> dict:
    """Analyse one AI answer.

    Returns {'mentioned': bool, 'placement': float|None (0=top),
             'competitors': [...], 'score': 0..100}.
    """
    domain = domain_of(website or "")
    mentioned, pos_frac = _find_mention(answer or "", business_name or "", domain)
    domain_cited = bool(domain) and domain in (answer or "").lower()
    competitors = _extract_competitors(answer or "", business_name or "", domain)
    return {
        "mentioned": mentioned,
        "placement": round(pos_frac, 3) if pos_frac is not None else None,
        "competitors": competitors,
        "score": _score(mentioned, pos_frac, domain_cited),
    }


# ---------------------------------------------------------- prompt pack ----
def build_prompt_pack(business_name: str, website: str, phrases: list) -> dict:
    """Neutral copy-paste prompts (one per phrase) for the manual path.

    The prompts never name the client's business — same honest measurement
    as the automated checks.
    """
    prompts = [NEUTRAL_PROMPT.format(phrase=p) for p in phrases if p.strip()]
    return {"chatgpt": prompts, "perplexity": prompts, "gemini": prompts}
