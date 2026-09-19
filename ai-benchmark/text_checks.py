"""Deterministic text checks (grader v2) for Assistive text actions.

Goes beyond length/keyword ratios:
  - typo_fix_rate: were the *injected* typos actually corrected?
  - protected_tokens: were technical tokens (ATT&CK ids, URLs, hashes, CVEs,
    IPs, <code> spans) left untouched?
  - n-gram repetition (makeLonger failure mode: padding by copying input)
  - novelty ratio (new content really added?)
  - claims_required / claims_forbidden: meaning-level guard against
    keyword-overlap passing while flipping meaning ("confirmed" -> "not confirmed").
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*")

PROTECTED_PATTERNS = [
    re.compile(r'\bT\d{4}(?:\.\d{3})?\b'),                       # ATT&CK technique ids
    re.compile(r'\bCVE-\d{4}-\d{4,}\b', re.I),                   # CVEs
    re.compile(r'\b[0-9a-f]{32,64}\b'),                          # hashes
    re.compile(r'\b\d{1,3}(?:\.\d{1,3}){3}\b'),                  # IPv4
    re.compile(r'\b(?:https?://|www\.)[^\s)>\]]+', re.I),        # URLs
    re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.]+\b'),                  # emails
    re.compile(r'\b(?:[\w-]+\.)+[a-z]{2,}\b', re.I),             # domains
    re.compile(r'<code>.*?</code>', re.S | re.I),                # code spans
]


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text or '')


def typo_pairs(source: str, reference: str) -> list[tuple[str, str]]:
    """(wrong, right) word pairs derived by diffing corrupted input vs clean reference.

    'wrong' == '' means an extra word was inserted in the input.
    """
    sm = SequenceMatcher(None, tokenize(source), tokenize(reference))
    pairs: list[tuple[str, str]] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'replace':
            src_w, ref_w = tokenize(source)[i1:i2], tokenize(reference)[j1:j2]
            for k in range(max(len(src_w), len(ref_w))):
                w = src_w[k].lower() if k < len(src_w) else ''
                r = ref_w[k].lower() if k < len(ref_w) else ''
                if w and w != r:
                    pairs.append((w, r))
        elif op == 'delete':
            for w in tokenize(source)[i1:i2]:
                pairs.append((w.lower(), ''))
        elif op == 'insert':
            for r in tokenize(reference)[j1:j2]:
                pairs.append(('', r.lower()))
    return pairs


def typo_fix_rate(output: str, source: str, reference: str) -> tuple[float, int]:
    """Fraction of injected corruptions repaired in the output."""
    pairs = typo_pairs(source, reference)
    if not pairs:
        return 1.0, 0
    out_t = ' ' + ' '.join(tokenize(output)).lower() + ' '
    fixed = 0
    for wrong, right in pairs:
        if not wrong:            # pure insertion in input: output must keep the word
            fixed += 1 if right and f' {right} ' in out_t else 0
        elif right and f' {right} ' in out_t and f' {wrong} ' not in out_t:
            fixed += 1
        elif right and f' {right} ' in out_t:
            fixed += 0.5          # right word present but wrong word also still there
    return fixed / len(pairs), len(pairs)


def protected_tokens(text: str) -> list[str]:
    found: list[str] = []
    for pat in PROTECTED_PATTERNS:
        found.extend(m.group(0) for m in pat.finditer(text or ''))
    return found


def protected_token_damage(output: str, source: str) -> list[str]:
    """Protected tokens present in the input but lost/modified in the output."""
    out = output or ''
    return [t for t in protected_tokens(source) if t not in out]


def ngram_repeats(output: str, n: int = 10) -> int:
    grams: dict[tuple, int] = {}
    toks = [t.lower() for t in tokenize(output)]
    for i in range(len(toks) - n + 1):
        g = tuple(toks[i:i + n])
        grams[g] = grams.get(g, 0) + 1
    return sum(1 for c in grams.values() if c > 1)


def novelty_ratio(output: str, source: str, n: int = 10) -> float:
    """Share of output n-grams absent from the source (is new content really added?)."""
    out_t = [t.lower() for t in tokenize(output)]
    src_grams = {tuple([t.lower() for t in tokenize(source)][i:i + n])
                 for i in range(max(len(tokenize(source)) - n + 1, 0))}
    grams = [tuple(out_t[i:i + n]) for i in range(max(len(out_t) - n + 1, 0))]
    if not grams:
        return 0.0
    return sum(1 for g in grams if g not in src_grams) / len(grams)


def _norm(s: str) -> str:
    s = (s or '').lower()
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'[^a-z0-9а-я\u0600-\u06ff ]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


NEGATORS = {'not', 'never', 'no', 'cannot', 'without', 'neither', 'nor', 'unlikely', 'unconfirmed'}


def _norm_words(norm: str) -> list[tuple[str, int]]:
    return [(m.group(0), m.start()) for m in re.finditer(r'\S+', norm)]


def _contains_claim(norm_out: str, claim_norm: str) -> tuple[bool, bool]:
    """(found, negated) — substring match with a negation window (3 words) before it."""
    i = norm_out.find(claim_norm)
    if i == -1:
        return False, False
    words = _norm_words(norm_out)
    w_start = next((s for _, s in words if s >= i), i)
    idx = next((k for k, (_, s) in enumerate(words) if s == w_start), len(words))
    prev = [w for w, _ in words[max(0, idx - 3):idx]]
    negated = any(n in prev for n in NEGATORS) or any(w.endswith("n't") for w in prev)
    return True, negated


def claim_hits(output: str, claims: list[str]) -> list[str]:
    out = _norm(output)
    return [c for c in (claims or []) if _norm(c) in out]


def claims_ok(output: str, claims_required: list[str] | None, claims_forbidden: list[str] | None) -> tuple[bool, dict]:
    """Polarity-aware claim check.

    A required claim counts as missing when absent OR present only in negated
    form ("not been confirmed as ..."). A forbidden claim starting with a
    negator ('not confirmed') fires when the affirmative head appears negated
    in the output — catching meaning flips that plain keyword overlap misses.
    """
    out = _norm(output)
    missing, forbidden_found = [], []
    for c in (claims_required or []):
        cn = _norm(c)
        found, neg = _contains_claim(out, cn)
        if not found or neg:
            missing.append(c)
    for c in (claims_forbidden or []):
        cn = _norm(c)
        words = cn.split()
        head = cn
        for neg in ('not', 'never', 'no'):
            if words and words[0] == neg:
                head = ' '.join(words[1:])
                break
        contiguous = cn in out
        if head and head != cn:
            found_head, head_negated = _contains_claim(out, head)
            if (found_head and head_negated) or contiguous:
                forbidden_found.append(c)
        elif contiguous:
            forbidden_found.append(c)
    return (not missing and not forbidden_found), {'required_missing': missing, 'forbidden_found': forbidden_found}


def unchanged_word_preservation(output: str, reference: str, min_sim: float = 0.75) -> float:
    return SequenceMatcher(None, (output or '').lower(), (reference or '').lower()).ratio()
