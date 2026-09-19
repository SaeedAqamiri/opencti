"""Expand the benchmark toward the 60-80 item target (review 2026-09-17, section 3).

Everything is generated deterministically from the FROZEN datasets — no hand-made
goldens. New cases are suite='heldout' (never used for prompt/tool tuning);
the existing 21 regression items stay untouched.

Outputs:
  cases/text_actions_expanded.json    6 -> 18 (each action x 2 more scenarios)
  cases/container_report_expanded.json 1 -> 2
  cases/insights_expanded.json        2 -> 4 checks (APT28, Lazarus)
  cases/nlq_expanded.json             5 -> 17
  agent_bench/tasks_expanded.json     +10 agent tasks (merged into tasks_v2 by compute_goldens_v2.py)
"""
from __future__ import annotations

import json
import random
import re
from collections import defaultdict
from pathlib import Path

import text_checks as tc

HERE = Path(__file__).parent
DATA = HERE / 'data'
CASES = HERE / 'cases'
AGENT = HERE / 'agent_bench'

attack = json.load(open(DATA / 'enterprise-attack-2026-09-15.json'))
otx = json.load(open(DATA / 'otx-snapshot-2026-09-16.json'))
objs = {o['id']: o for o in attack['objects']}
by_name = defaultdict(list)
for o in attack['objects']:
    if o.get('name'):
        by_name[o['name']].append(o)

is_ids = {o['name']: o['id'] for o in attack['objects'] if o['type'] == 'intrusion-set'}
out_uses = defaultdict(set)
in_mitigates = defaultdict(set)
attributed = defaultdict(set)
for r in attack['objects']:
    if r['type'] != 'relationship':
        continue
    s, t = r['source_ref'], r['target_ref']
    if r['relationship_type'] == 'uses':
        out_uses[s].add(t)
    elif r['relationship_type'] == 'mitigates':
        in_mitigates[t].add(s)
    elif r['relationship_type'] == 'attributed-to':
        attributed[s].add(t)


def name(i):
    return objs[i].get('name') if i in objs else None


def names_of(gid_, prefix):
    return sorted({name(t) for t in out_uses[gid_] if t.startswith(prefix) and name(t)})


def ids_and_names(gid_, prefix):
    out = []
    for t in sorted(out_uses[gid_]):
        if t.startswith(prefix) and name(t):
            out.append((t, name(t)))
    return out


# ───────────────────────── phase 4: NLQ expansion (12 new) ───────────────

def nlq_case(cid, question, ents, etype):
    ents = sorted(set(ents))
    return {'id': cid, 'suite': 'heldout', 'question': question,
            'golden_ids': [i for i, _ in ents], 'golden_names': [n for _, n in ents],
            'expect_entity_type': etype}


nlq_expanded = []
GROUP_SPECS = [
    ('nlq-x-lazarus-tools', 'Which tools are used by Lazarus Group?', 'Lazarus Group', 'tool--', 'Tool'),
    ('nlq-x-apt29-tools', 'Which tools are used by APT29?', 'APT29', 'tool--', 'Tool'),
    ('nlq-x-oilrig-malware', 'Which malware is used by OilRig?', 'OilRig', 'malware--', 'Malware'),
    ('nlq-x-sandworm-malware', 'Which malware is used by Sandworm Team?', 'Sandworm Team', 'malware--', 'Malware'),
    ('nlq-x-apt41-tools', 'Which tools are used by APT41?', 'APT41', 'tool--', 'Tool'),
    ('nlq-x-turla-techniques', 'Which attack patterns does Turla use?', 'Turla', 'attack-pattern--', 'Attack-Pattern'),
    ('nlq-x-lazarus-techniques', 'Which attack patterns does Lazarus Group use?', 'Lazarus Group', 'attack-pattern--', 'Attack-Pattern'),
]
for cid, q, g, prefix, etype in GROUP_SPECS:
    gid_ = is_ids.get(g)
    if not gid_:
        continue
    ents = ids_and_names(gid_, prefix)
    if ents:
        nlq_expanded.append(nlq_case(cid, q, ents, etype))

# set-intersection between other group pairs
PAIRS = [('nlq-x-shared-malware-apt29-lazarus', 'APT29', 'Lazarus Group', 'malware--'),
         ('nlq-x-shared-tools-apt28-lazarus', 'APT28', 'Lazarus Group', 'tool--')]
for cid, g1, g2, prefix in PAIRS:
    i1, i2 = is_ids.get(g1), is_ids.get(g2)
    if not (i1 and i2):
        continue
    shared = {n for _, n in ids_and_names(i1, prefix)} & {n for _, n in ids_and_names(i2, prefix)}
    ents = [(i, n) for i, n in ids_and_names(i1, prefix) if n in shared]
    if ents:
        nlq_expanded.append(nlq_case(cid, f'Which {"tools" if prefix == "tool--" else "malware families"} are used by BOTH {g1} and {g2}?', ents,
                                     'Tool' if prefix == 'tool--' else 'Malware'))

# COAs mitigating other techniques
COA_TECHNIQUES = [('nlq-x-coa-valid-accounts', 'Valid Accounts', 'T1078'),
                  ('nlq-x-coa-spearphishing-attachment', 'Spearphishing Attachment', 'T1566.001'),
                  ('nlq-x-coa-exploit-public-facing', 'Exploit Public-Facing Application', 'T1190')]
for cid, tech_name, ext_id in COA_TECHNIQUES:
    tech = next((o for o in by_name.get(tech_name, [])
                 if o['type'] == 'attack-pattern'
                 and ((o.get('external_references') or [{}])[0].get('external_id') == ext_id)), None)
    if not tech:
        continue
    coas = sorted({name(c) for c in in_mitigates.get(tech['id'], set())
                   if c.startswith('course-of-action--') and name(c)})
    if coas:
        ids = [c for c in in_mitigates.get(tech['id'], set()) if name(c)]
        nlq_case_new = nlq_case(cid, f'Which courses of action mitigate the {tech_name} technique?',
                                list(zip(ids, coas)), 'Course-Of-Action')
        nlq_expanded.append(nlq_case_new)

# groups sharing >= N techniques with another group
NEIGHBOR_SPECS = [('nlq-x-neighbors-apt28', 'APT28', 20), ('nlq-x-neighbors-lazarus', 'Lazarus Group', 15)]
for cid, g, thresh in NEIGHBOR_SPECS:
    gid_ = is_ids.get(g)
    if not gid_:
        continue
    g_techs = {t for t in out_uses[gid_] if t.startswith('attack-pattern--')}
    found = []
    for o in attack['objects']:
        if o['type'] == 'intrusion-set' and o['name'] != g:
            its = {t for t in out_uses[o['id']] if t.startswith('attack-pattern--')}
            if len(its & g_techs) >= thresh:
                found.append((o['id'], o['name']))
    if found:
        nlq_expanded.append(nlq_case(cid, f'Which intrusion sets share at least {thresh} techniques with {g}?', found, 'Intrusion-Set'))

CASES.joinpath('nlq_expanded.json').write_text(json.dumps(nlq_expanded, indent=2, ensure_ascii=False))
print(f'nlq_expanded: {len(nlq_expanded)} cases')

# ───────────────────── phase 1: text actions expansion (12 new) ──────────

def find_attack_pattern(ext_id):
    for o in attack['objects']:
        if o['type'] == 'attack-pattern' and (o.get('external_references') or [{}]):
            for er in o.get('external_references', []):
                if er.get('external_id') == ext_id:
                    return o
    return None


def clean_description(o, max_chars=1600):
    d = re.sub(r'\(Citation:[^)]*\)', '', o.get('description', ''))
    d = re.sub(r'\n{3,}', '\n\n', d).strip()
    return d[:max_chars]


def corrupt(text: str, seed: int, n_swaps: int) -> str:
    """Deterministic typo injection: adjacent-letter swaps on safe words."""
    spans_protected = []
    for pat in tc.PROTECTED_PATTERNS:
        spans_protected.extend((m.start(), m.end()) for m in pat.finditer(text))
    words = [(m.start(), m.end()) for m in re.finditer(r'\b[a-z]{4,}\b', text)]
    rng = random.Random(seed)
    candidates = [(s, e) for s, e in words if not any(ps <= s and e <= pe for ps, pe in spans_protected)]
    out = list(text)
    swapped = 0
    tries = 0
    while swapped < n_swaps and candidates and tries < 500:
        tries += 1
        s, e = rng.choice(candidates)
        if e - s < 2:
            continue
        i = rng.randrange(s, e - 1)
        if out[i] == out[i + 1]:
            continue
        out[i], out[i + 1] = out[i + 1], out[i]
        swapped += 1
    return ''.join(out)


def first_claim(text: str) -> str:
    """Lead-clause of the first sentence — the summary must cover it."""
    first = re.split(r'(?<=[.!?])\s', text.strip())[0]
    lead = re.split(r',|;|:|\s—\s|\(', first)[0].strip()
    return lead[:140]


TECH_SPECS = [
    ('T1566', 'Phishing'), ('T1059', 'Command and Scripting Interpreter'),
    ('T1078', 'Valid Accounts'), ('T1486', 'Data Encrypted for Impact'),
    ('T1190', 'Exploit Public-Facing Application'), ('T1552', 'Unsecured Credentials'),
]
texts = {}
for ext_id, _ in TECH_SPECS:
    o = find_attack_pattern(ext_id)
    if o:
        texts[ext_id] = clean_description(o)
keys = [k for k in texts]
print(f'technique texts: {len(texts)} ({", ".join(keys)})')

text_expanded = []
seeds = iter([43, 44, 45, 46, 47, 48])
k = 0
for action in ['fixSpelling', 'fixSpelling', 'makeShorter', 'makeLonger',
               'changeTone', 'changeTone', 'summarize', 'summarize',
               'explain', 'explain', 'makeShorter', 'summarize']:
    if k >= len(keys) * 2:
        break
    ext_id = keys[k % len(keys)]
    body = texts[ext_id]
    cid = f'x-{action.lower()}-{ext_id.lower()}-{k}'
    case = {'id': cid, 'suite': 'heldout', 'action': action, 'format': 'text'}
    if action == 'fixSpelling':
        case['input'] = corrupt(body, next(seeds), 12)
        case['reference'] = body
        case['source_technique'] = ext_id
    elif action == 'summarize':
        case['input'] = body
        case['claims_required'] = [first_claim(body)]
        absent_group = 'Fancy Bear' if 'fancy bear' not in body.lower() else 'Cozy Bear'
        case['claims_forbidden'] = [absent_group]
        case['source_technique'] = ext_id
    elif action == 'makeShorter':
        case['input'] = body
        case['claims_required'] = [first_claim(body)]
        case['source_technique'] = ext_id
    elif action == 'makeLonger':
        case['input'] = body[:800]
        case['source_technique'] = ext_id
    elif action == 'changeTone':
        case['input'] = body
        case['tone'] = 'tactical' if k % 2 == 0 else 'strategic'
        case['source_technique'] = ext_id
    else:  # explain
        case['input'] = body
        case['source_technique'] = ext_id
    text_expanded.append(case)
    k += 1

CASES.joinpath('text_actions_expanded.json').write_text(json.dumps(text_expanded, indent=2, ensure_ascii=False))
print(f'text_actions_expanded: {len(text_expanded)} cases')

# ───────────────── phase 2 + 3: container report & insights (heldout) ────

def find_obj(name_, type_):
    return next((o for o in by_name.get(name_, []) if o['type'] == type_), None)


c2_objs = []
for nm, ty in [('Sandworm Team', 'intrusion-set'), ('Lazarus Group', 'intrusion-set'),
               ('Sunburst', 'malware'), ('Cobalt Strike', 'tool'), ('Phishing', 'attack-pattern')]:
    o = find_obj(nm, ty)
    if o:
        c2_objs.append({'id': o['id'], 'name': o['name'], 'type': ty})
container2 = {'container_name': 'AI Benchmark Container B', 'suite': 'heldout',
              'objects': c2_objs, 'entity_names': [o['name'] for o in c2_objs]}
CASES.joinpath('container_report_expanded.json').write_text(json.dumps(container2, indent=2, ensure_ascii=False))

ins_exp = []
for g in ['APT28', 'Lazarus Group']:
    o = find_obj(g, 'intrusion-set')
    if o:
        ins_exp.append({'suite': 'heldout',
                        'activity_target': {'id': o['id'], 'name': o['name']},
                        'history_target': {'id': o['id'], 'name': o['name']}})
CASES.joinpath('insights_expanded.json').write_text(json.dumps(ins_exp, indent=2, ensure_ascii=False))
print(f'container_report_expanded: 1 case ({len(c2_objs)} objects), insights_expanded: {len(ins_exp)} targets')

# ─────────────────── agent tasks expansion (10 new, heldout) ─────────────

def triples_for(group, rel, prefix):
    gid_ = is_ids.get(group)
    if not gid_:
        return []
    return sorted([[group, rel, n] for n in names_of(gid_, prefix)])


new_tasks = []
TASK_SPECS = [
    {'id': 't8-apt29-tools', 'type': 'retrieve',
     'question': 'Which tools does APT29 use? List each tool and cite entities.',
     'gold': lambda: (names_of(is_ids['APT29'], 'tool--'), triples_for('APT29', 'uses', 'tool--')),
     'max_calls': 6, 'universe': ('apt29-uses', 'APT29')},
    {'id': 't9-lazarus-malware', 'type': 'retrieve',
     'question': 'Which malware is used by Lazarus Group? Cite each family.',
     'gold': lambda: (names_of(is_ids['Lazarus Group'], 'malware--'), triples_for('Lazarus Group', 'uses', 'malware--')),
     'max_calls': 8, 'universe': ('lazarus-group-uses', 'Lazarus Group')},
    {'id': 't10-shared-tools-apt28-lazarus', 'type': 'retrieve',
     'question': 'Which tools are used by BOTH APT28 and Lazarus Group?',
     'gold': lambda: (sorted({n for n in names_of(is_ids['APT28'], 'tool--')}
                             & {n for n in names_of(is_ids['Lazarus Group'], 'tool--')}), []),
     'max_calls': 10, 'universe': None},
    {'id': 't11-sandworm-coa', 'type': 'multi_hop',
     'question': 'Which courses of action mitigate the techniques that Sandworm Team uses?',
     'gold': lambda: (sorted({name(c) for t in out_uses[is_ids['Sandworm Team']] if t.startswith('attack-pattern--')
                              for c in in_mitigates.get(t, set()) if c.startswith('course-of-action--') and name(c)}), []),
     'max_calls': 14, 'universe': None},
    {'id': 't12-neighbors-apt28-20', 'type': 'retrieve',
     'question': 'Which intrusion sets share at least 20 techniques with APT28?',
     'gold': lambda: (sorted([o['name'] for o in attack['objects'] if o['type'] == 'intrusion-set' and o['name'] != 'APT28'
                              and len({t for t in out_uses[o['id']] if t.startswith('attack-pattern--')}
                                      & {t for t in out_uses[is_ids['APT28']] if t.startswith('attack-pattern--')}) >= 20]), []),
     'max_calls': 12, 'universe': None},
    {'id': 't13-profile-apt29', 'type': 'profile',
     'question': 'Build a profile of APT29: attributed campaigns, malware, tools, and the number of distinct techniques.',
     'gold': lambda: (sorted({'APT29', *{name(c) for c in attributed[is_ids['APT29']] if name(c)},
                              *{name(m) for m in out_uses[is_ids['APT29']] if m.startswith('malware--') and name(m)}}), []),
     'max_calls': 14, 'universe': ('apt29-uses', 'APT29')},
]
for spec in TASK_SPECS:
    gid_src = spec.get('universe')
    try:
        gold_names, gold_triples = spec['gold']()
    except KeyError:
        continue
    if not gold_names:
        continue
    task = {'id': spec['id'], 'type': spec['type'], 'suite': 'heldout',
            'question': spec['question'],
            'gold_entity_names': gold_names, 'gold_triples': gold_triples,
            'max_calls': spec['max_calls'], 'policy': {}}
    if gid_src:
        u_key, u_group = gid_src
        task['policy']['claim_universe'] = u_key
        task['policy']['anchor_entity'] = u_group
    new_tasks.append(task)

# OTX IOC investigation for other targets
otx_links = defaultdict(set)
for o in otx['objects']:
    if o['type'] == 'relationship' and o['relationship_type'] == 'related-to':
        tgt = objs.get(o['target_ref'])
        if tgt and tgt.get('name'):
            otx_links[tgt['name']].add(o['source_ref'])
IND_SPECS = [('t14-investigate-ioc-apt29', 'APT29', 'apt29-uses'),
             ('t15-investigate-ioc-kimsuky', 'Kimsuky', 'kimsuky-uses')]  # OTX snapshot only links these + APT28
for cid, group, u_key in IND_SPECS:
    ind_id = next(iter(otx_links.get(group, [])), None)
    if not ind_id:
        continue
    ind = next((o for o in otx['objects'] if o['type'] == 'indicator' and o['id'] == ind_id), None)
    if not ind:
        continue
    hash_ = ind['pattern'].split("'")[1] if "'" in ind['pattern'] else ind['pattern']
    new_tasks.append({
        'id': cid, 'type': 'investigate', 'suite': 'heldout',
        'question': f"Investigate this indicator and tell me which threat group it is linked to and two techniques that group uses: {ind['pattern']}",
        'gold_entity_names': [group], 'gold_triples': [], 'max_calls': 12,
        'policy': {'claim_universe': u_key, 'anchor_entity': group,
                   'accept_any_valid_techniques': 2, 'require_link_evidence': True,
                   'indicator_marker': hash_, 'triple_recall_min': 0.0, 'triple_precision_min': 0.0},
    })

# exact-technique-count profile task for APT29
apt29 = is_ids.get('APT29')
if apt29:
    seen, cnt = set(), 0
    for t in out_uses.get(apt29, set()):
        o = objs.get(t)
        if not o or o.get('type') != 'attack-pattern' or o.get('x_mitre_deprecated') or o.get('revoked'):
            continue
        ext = (o.get('external_references') or [{}])[0].get('external_id') or o['id']
        if ext not in seen:
            seen.add(ext)
            cnt += 1
    t13 = next((t for t in new_tasks if t['id'] == 't13-profile-apt29'), None)
    if t13 and cnt > 0:
        t13['policy']['technique_count_exact'] = cnt
        t13['policy']['technique_count_tolerance'] = 1
        print(f'APT29 exact techniques: {cnt}')

AGENT.joinpath('tasks_expanded.json').write_text(json.dumps(new_tasks, indent=2, ensure_ascii=False))
print(f'tasks_expanded: {len(new_tasks)} agent tasks')
