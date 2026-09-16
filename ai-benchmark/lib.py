"""Shared helpers: GraphQL client, scoring primitives."""
import difflib
import json
import os
import re

import requests

ENV_FILE = '/tmp/opencode/opencti-admin.env'


def load_env():
    env = {}
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            if '=' in line:
                k, v = line.strip().split('=', 1)
                env[k] = v
    return env


ENV = load_env()
URL = os.environ.get('OPENCTI_URL', ENV.get('URL', 'http://localhost:4000'))
TOKEN = os.environ.get('OPENCTI_TOKEN', ENV.get('TOKEN', ''))


def gql(query: str, variables: dict | None = None, timeout: int = 240):
    res = requests.post(
        URL + '/graphql',
        json={'query': query, 'variables': variables or {}},
        headers={'Authorization': f'Bearer {TOKEN}', 'Content-Type': 'application/json'},
        timeout=timeout,
    )
    data = res.json()
    if data.get('errors'):
        raise RuntimeError(json.dumps(data['errors'])[:500])
    return data['data']


# ── scoring primitives ────────────────────────────────────────────────────

def check(name: str, ok: bool, detail: str = '') -> dict:
    return {'check': name, 'pass': bool(ok), 'detail': detail}


def length_ratio(out: str, src: str) -> float:
    if not src:
        return 0.0
    return len(out) / max(len(src), 1)


def word_overlap(out: str, src: str, top_n: int = 10) -> float:
    """Share of src's top-N content words that appear in out."""
    stop = set('the a an of to in on and or is are be been was were for with by from as at that this it its '
               'their has have had not they them which who whom whose via into over under more most other '
               'than then also using used use may can could would should new known typically often'.split())
    words = [w.strip('.,;:()[]"\u2019\u2018\u201c\u201d').lower() for w in src.split()]
    words = [w for w in words if len(w) > 2 and w not in stop and not w.isdigit()]
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    top = [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:top_n]]
    out_l = out.lower()
    hits = sum(1 for w in top if w in out_l)
    return hits / max(len(top), 1)


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def has_html(text: str) -> bool:
    return bool(re.search(r'<[a-z][^>]*>', text, re.I))


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def case_score(checks: list[dict]) -> float:
    if not checks:
        return 0.0
    return sum(1 for c in checks if c['pass']) / len(checks)
