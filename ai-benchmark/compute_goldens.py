"""Compute golden answers for the benchmark from the ATT&CK STIX bundle.

Outputs:
  cases/text_actions.json  (phase 1 cases, texts taken from real ATT&CK content)
  cases/nlq.json           (phase 4 cases: question -> golden object id set)
  cases/insights.json      (phase 3 targets: entities with the richest graphs)
  cases/container_report.json (phase 2 container composition)
"""
import json
import random
from collections import defaultdict
from pathlib import Path

BUNDLE = '/tmp/opencode/enterprise-attack.json'
OUT = Path(__file__).parent / 'cases'
OUT.mkdir(exist_ok=True)

bundle = json.load(open(BUNDLE))
objects = bundle['objects']
by_id = {o['id']: o for o in objects}

sdos = defaultdict(list)
for o in objects:
    sdos[o['type']].append(o)

def name_of(obj_id):
    o = by_id.get(obj_id)
    return o.get('name') if o else None

# ── relationship index ────────────────────────────────────────────────────
rels = [o for o in objects if o['type'] == 'relationship']
uses_src_type = defaultdict(set)      # (src_type) -> set(dst_type) via uses
out_uses = defaultdict(set)           # src id -> set of dst ids (uses)
in_uses = defaultdict(set)            # dst id -> set of src ids (uses)
mitigates = defaultdict(set)          # dst id -> set of src ids (coa mitigates X)
for r in rels:
    s, d = r['source_ref'], r['target_ref']
    st, dt = s.split('--')[0], d.split('--')[0]
    if r['relationship_type'] == 'uses':
        out_uses[s].add(d)
        in_uses[d].add(s)
        uses_src_type[st].add(dt)
    if r['relationship_type'] == 'mitigates':
        mitigates[d].add(s)

# ── NLQ goldens ───────────────────────────────────────────────────────────
def ids_by_name(t, pattern):
    return {o['id'] for o in sdos[t] if pattern.lower() in o.get('name', '').lower()}

t1566 = {o['id'] for o in sdos['attack-pattern']
         if any(e.get('external_id') == 'T1566' for e in o.get('external_references', []))}
phishing_users = set()
for ap in t1566:
    phishing_users |= {s for s in in_uses.get(ap, set()) if s.startswith('intrusion-set--')}

apt28 = ids_by_name('intrusion-set', 'APT28')
apt29 = ids_by_name('intrusion-set', 'APT29')
apt28_tools, apt28_malware = set(), set()
for i in apt28:
    apt28_tools |= {d for d in out_uses.get(i, set()) if d.startswith('tool--')}
    apt28_malware |= {d for d in out_uses.get(i, set()) if d.startswith('malware--')}
apt29_patterns = set()
for i in apt29:
    apt29_patterns |= {d for d in out_uses.get(i, set()) if d.startswith('attack-pattern--')}

zebrocy = ids_by_name('malware', 'Zebrocy')
zebrocy_coas = set()
for m in zebrocy:
    zebrocy_coas |= {s for s in mitigates.get(m, set()) if s.startswith('course-of-action--')}
if not zebrocy_coas:  # fallback: COAs mitigating the Phishing technique
    for ap in ids_by_name('attack-pattern', 'Phishing'):
        zebrocy_coas |= {s for s in mitigates.get(ap, set()) if s.startswith('course-of-action--')}

def names_of(ids):
    return sorted({by_id[i].get('name') for i in ids if i in by_id and by_id[i].get('name')})


nlq_cases = [
    {
        'id': 'nlq-phishing-intrusion-sets',
        'question': 'Which intrusion sets use phishing techniques?',
        'golden_ids': sorted(phishing_users),
        'expect_entity_type': 'Intrusion-Set',
    },
    {
        'id': 'nlq-apt28-tools',
        'question': 'Which tools are used by APT28?',
        'golden_ids': sorted(apt28_tools),
        'expect_entity_type': 'Tool',
    },
    {
        'id': 'nlq-apt28-malware',
        'question': 'Which malware is used by APT28?',
        'golden_ids': sorted(apt28_malware),
        'expect_entity_type': 'Malware',
    },
    {
        'id': 'nlq-apt29-attack-patterns',
        'question': 'Which attack patterns does APT29 use?',
        'golden_ids': sorted(apt29_patterns),
        'expect_entity_type': 'Attack-Pattern',
    },
    {
        'id': 'nlq-zebrocy-mitigations',
        'question': 'Which courses of action mitigate the Zebrocy malware?',
        'golden_ids': sorted(zebroco := zebrocy_coas),
        'expect_entity_type': 'Course-Of-Action',
    },
]
for c in nlq_cases:
    c['golden_names'] = names_of(c['golden_ids'])
json.dump(nlq_cases, open(OUT / 'nlq.json', 'w'), indent=2)

# ── text actions (phase 1) ────────────────────────────────────────────────
aps = [o for o in sdos['attack-pattern'] if len(o.get('description', '')) > 400]
aps.sort(key=lambda o: -len(o['description']))
src1, src2, src3 = aps[0]['description'], aps[1]['description'], aps[2]['description']

random.seed(42)
def corrupt(text: str) -> str:
    words = text.split()
    idxs = [i for i, w in enumerate(words) if len(w) > 4 and w.isalpha()]
    for i in random.sample(idxs, min(12, len(idxs))):
        w = words[i]
        words[i] = w[0] + w[2] + w[1] + w[3:]  # swap two letters
    return ' '.join(words)

text_cases = [
    {'id': 'fix-1', 'action': 'fixSpelling', 'input': corrupt(src1[:1200]), 'format': 'text',
     'reference': src1[:1200]},
    {'id': 'shorter-1', 'action': 'makeShorter', 'input': src1, 'format': 'text'},
    {'id': 'longer-1', 'action': 'makeLonger', 'input': src2[:600], 'format': 'text'},
    {'id': 'tone-1', 'action': 'changeTone', 'input': src3[:900], 'format': 'text', 'tone': 'strategic'},
    {'id': 'summarize-1', 'action': 'summarize', 'input': src1, 'format': 'text'},
    {'id': 'explain-1', 'action': 'explain', 'input': src2[:900]},
]
json.dump(text_cases, open(OUT / 'text_actions.json', 'w'), indent=2)

# ── insights + container report targets ───────────────────────────────────
top_is = max(sdos['intrusion-set'], key=lambda o: len(out_uses.get(o['id'], set())))
insights = {
    'activity_target': {'id': top_is['id'], 'name': top_is['name']},
    'history_target': {'id': top_is['id'], 'name': top_is['name']},
}
json.dump(insights, open(OUT / 'insights.json', 'w'), indent=2)

def pick(t, n, exclude=()):
    out = [o for o in sdos[t] if o['id'] not in exclude]
    out.sort(key=lambda o: -len(o.get('description', '')))
    return out[:n]

container_objects = (
    pick('intrusion-set', 2) + pick('malware', 3) + pick('attack-pattern', 4) + pick('tool', 1)
)
container_case = {
    'container_name': 'AI Benchmark Container',
    'objects': [{'id': o['id'], 'name': o.get('name'), 'type': o['type']} for o in container_objects],
    'entity_names': [o.get('name') for o in container_objects if o.get('name')],
}
json.dump(container_case, open(OUT / 'container_report.json', 'w'), indent=2)

print('goldens written:')
print('  nlq cases:', len(nlq_cases),
      '| sizes:', [len(c['golden_ids']) for c in nlq_cases])
print('  apt28 tools:', len(apt28_tools), '| apt28 malware:', len(apt28_malware),
      '| phishing users:', len(phishing_users))
print('  activity target:', top_is['name'], 'uses->', len(out_uses.get(top_is['id'], set())))
print('  container objects:', len(container_objects))
