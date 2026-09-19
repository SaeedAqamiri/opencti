"""Build cases/v2/file2stix.json — deterministic case set for the file→STIX suite.

Two frozen CISA advisories (gold: official CISA STIX IOC set + text regex techniques)
plus one synthetic narrative whose gold triples come from the committed gold-graph
fixture (extraction target: entities, relations, decoys that must NOT be extracted).

Deterministic: narrative sentences are generated from fixture.json in fixed order;
running twice produces byte-identical output (asserted).
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
V2 = HERE / 'cases' / 'v2'
FIXTURE = HERE / 'gold_graph' / 'fixture.json'

# narrative plan: entities mentioned, relations asserted, decoys held out.
# 'Alpha Group' tool (alpha-name-tool) is excluded entirely — its display name
# collides with an alias of alpha-group and would make extraction ambiguous.
MENTION = ['alpha-group', 'm1', 'probe-tool', 'dep-technique', 'campaign-1', 'beta-group']
RELATIONS = [('alpha-group', 'uses', 'm1'),
             ('alpha-group', 'uses', 'probe-tool'),
             ('alpha-group', 'uses', 'dep-technique'),
             ('campaign-1', 'attributed-to', 'alpha-group')]
DECOYS = ['m2', 'unused-technique', 'injection-report']

TYPE_LABEL = {'intrusion-set': 'threat group', 'malware': 'malware family',
              'tool': 'tool', 'attack-pattern': 'attack technique',
              'campaign': 'campaign operation', 'report': 'report',
              'indicator': 'indicator'}


def build_narrative() -> tuple[str, dict]:
    fx = json.load(open(FIXTURE))
    ents = {e['key']: e for e in fx['entities']}

    def name(key):
        return ents[key]['display_name']

    lines = ['# Internal incident report 2026-09-19', '']
    lines.append(f'Our team tracked {name("campaign-1")}, a campaign operation '
                 f'observed between June and August of this year.')
    for key in MENTION:
        e = ents[key]
        label = TYPE_LABEL.get(e['type'], e['type'])
        lines.append(f'The {label} {name(key)} was documented in our telemetry during the intrusion.')
    lines.append('')
    lines.append('## Findings')
    for src, rel, dst in RELATIONS:
        verb = {'uses': 'uses', 'attributed-to': 'is attributed to',
                'related-to': 'is related to'}.get(rel, rel)
        lines.append(f'- We assess with high confidence that {name(src)} {verb} {name(dst)}.')
    lines.append('')
    lines.append('Indicators of compromise were collected from customer sandboxes and '
                 'shared with the constituency. No further links between the tooling '
                 'clusters were identified at the time of writing.')
    text = '\n'.join(lines) + '\n'

    gold = {
        'entity_gold': sorted(name(k) for k in MENTION),
        'relation_gold': [[name(s), r, name(d)] for s, r, d in RELATIONS],
        'decoy_names': sorted(name(k) for k in DECOYS),
    }
    return text, gold


def main():
    V2.mkdir(parents=True, exist_ok=True)
    narrative, gold = build_narrative()

    cases = [
        {'id': 'f2s-cisa-347a', 'kind': 'cisa', 'advisory': 'aa23-347a',
         'ioc_recall_gate': 0.5, 'hallucination_gate': 0.2, 'technique_recall_gate': 0.7,
         'suite': 'regression'},
        {'id': 'f2s-cisa-320a', 'kind': 'cisa', 'advisory': 'aa22-320a',
         'ioc_recall_gate': 0.5, 'hallucination_gate': 0.2, 'technique_recall_gate': 0.7,
         'suite': 'regression'},
        {'id': 'f2s-narrative-goldgraph', 'kind': 'narrative',
         'text': narrative, 'entity_gold': gold['entity_gold'],
         'relation_gold': gold['relation_gold'], 'decoy_names': gold['decoy_names'],
         'entity_recall_gate': 0.8, 'relation_recall_gate': 0.5, 'decoy_max': 0,
         'suite': 'regression'},
    ]
    out = V2 / 'file2stix.json'
    out.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + '\n')
    # determinism assertion
    assert json.loads(out.read_text()) == cases
    print('wrote', out, f'({len(cases)} cases; narrative {len(narrative)} chars, '
          f'{len(gold["entity_gold"])} entities, {len(gold["relation_gold"])} relations, '
          f'{len(gold["decoy_names"])} decoys)')


if __name__ == '__main__':
    main()
