"""Build the mini gold graph in a live OpenCTI instance (or print the plan).

Every created object is recorded in agent_bench/identity_map.json with
provenance=gold-graph and its platform-assigned opencti_identifier, so the
grader can resolve names/aliases to platform ids and so hand-built relations
stay distinguishable from source-native ones.

Usage:
  python3 build_graph.py --dry-run     # print planned mutations (no network)
  python3 build_graph.py               # create entities + relations, then record ids
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))  # ai-benchmark/ for identity_map + lib
FIXTURE = json.load(open(HERE / 'fixture.json'))
NS = uuid.UUID(FIXTURE['uuid_namespace'])
STIX_TYPE = {'intrusion-set': 'intrusion-set', 'malware': 'malware', 'tool': 'tool',
             'attack-pattern': 'attack-pattern', 'campaign': 'campaign',
             'report': 'report', 'indicator': 'indicator', 'sector': 'identity'}


def gid(key: str) -> str:
    """Deterministic UUID **in v4 format** (version+variant nibbles patched) — platform validates v4."""
    h = list(uuid.uuid5(NS, f'opencti-bench:{key}').hex)
    h[12] = '4'
    h[16] = '8'
    s = ''.join(h)
    return f'{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}'


def stix_id(entity_type: str, key: str) -> str:
    return f'{STIX_TYPE[entity_type]}--{gid(key)}'


def expand(fixture: dict):
    """Expand the indicator range entity into concrete entities/relations."""
    entities, relations = [], []
    for e in fixture['entities']:
        if 'range' in e:
            lo, hi = e['range']['from'], e['range']['to']
            for i in range(lo, hi + 1):
                entities.append({**e, 'key': f"ind-{i:03d}", 'display_name': e['display_name'].format(i=i),
                                 'pattern': e['pattern_template'].format(i=i)})
                del entities[-1]['range'], entities[-1]['pattern_template']
        else:
            entities.append(dict(e))
    for r in fixture['relations']:
        if r.get('expand'):
            lo, hi = next(x['range'] for x in fixture['entities'] if x['key'] == r['from'])['from'], \
                     next(x['range'] for x in fixture['entities'] if x['key'] == r['from'])['to']
            for i in range(lo, hi + 1):
                relations.append({**r, 'from': f"ind-{i:03d}"})
        else:
            relations.append(dict(r))
    return entities, relations


ADD_MUTATIONS = {
    'intrusion-set': ('intrusionSetAdd', 'IntrusionSetAddInput'),
    'malware': ('malwareAdd', 'MalwareAddInput'),
    'tool': ('toolAdd', 'ToolAddInput'),
    'attack-pattern': ('attackPatternAdd', 'AttackPatternAddInput'),
    'campaign': ('campaignAdd', 'CampaignAddInput'),
    'report': ('reportAdd', 'ReportAddInput'),
    'indicator': ('indicatorAdd', 'IndicatorAddInput'),
    'sector': ('sectorAdd', 'SectorAddInput'),
}


def plan() -> list[dict]:
    entities, relations = expand(FIXTURE)
    by_key = {e['key']: e for e in entities}
    ops = []
    for e in entities:
        mut, inp = ADD_MUTATIONS[e['type']]
        name_field = 'name'
        payload: dict = {'name': e['display_name'], 'description': e.get('description', ''),
                         'stix_id': stix_id(e['type'], e['key'])}
        if e['type'] == 'attack-pattern':
            payload['x_mitre_id'] = e.get('external_id')
            if e.get('deprecated'):
                payload['description'] += ' [DEPRECATED technique — policy test]'  # AttackPatternAddInput has no x_mitre_deprecated
        if e['type'] == 'indicator':
            payload = {'name': e['display_name'], 'pattern': e['pattern'],
                       'pattern_type': 'stix', 'stix_id': stix_id('indicator', e['key'])}
        if e['type'] == 'report':
            payload['published'] = '2026-03-01T00:00:00.000Z'
        if e['type'] == 'malware':
            payload['is_family'] = False   # MalwareAddInput has is_family; ToolAddInput does NOT
        ops.append({'op': 'create', 'entity': e['key'], 'type': e['type'],
                    'mutation': mut, 'input_type': inp, 'input': payload,
                    'stix_id': stix_id(e['type'], e['key']),
                    'idempotency': f'lookup-by-stix_id:{stix_id(e["type"], e["key"])}'})
    for r in relations:
        ops.append({'op': 'relate', 'key': f"{r['from']}--{r['type']}--{r['to']}",
                    'mutation': 'stixCoreRelationshipAdd',
                    'input': {'relationship_type': r['type'],
                              'stix_id': f'relationship--{gid(r["from"] + r["type"] + r["to"])}'},
                    'from_key': r['from'], 'to_key': r['to'],
                    'note': 'fromId/toId resolved to platform internal ids after entity creation'})
    return ops


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    ops = plan()
    if args.dry_run:
        print(json.dumps({'planned_operations': len(ops),
                          'entities': sum(1 for o in ops if o['op'] == 'create'),
                          'relations': sum(1 for o in ops if o['op'] == 'relate'),
                          'operations': ops}, indent=2)[:4000])
        return

    import identity_map as im_mod
    from lib import gql
    imap = im_mod.IdentityMap.load()
    id_by_key: dict[str, str] = {}
    for o in ops:
        if o['op'] != 'create':
            continue
        q = f'mutation B($input: {o["input_type"]}!) {{ {o["mutation"]}(input: $input) {{ id }} }}'
        try:
            data = gql(q, {'input': o['input']})
            oid = list(data.values())[0]['id']
        except RuntimeError as err:
            if 'Duplicate' not in str(err) and 'already exist' not in str(err):
                raise
            # idempotent re-run: look the entity up by our deterministic stix id
            sid = o['stix_id']
            d2 = gql('''query L($sid: [String]) { stixCoreObjects(filters: { key: standard_id
                          values: $sid operator: eq mode: and }) { edges { node { id } } } }''',
                     {'sid': [sid]})
            edges = d2['stixCoreObjects']['edges']
            if not edges:
                raise
            oid = edges[0]['node']['id']
            print(f"reused {o['entity']} -> {oid}")
        id_by_key[o['entity']] = oid
        e = next(x for x in FIXTURE['entities']
                 if x['key'] == o['entity'] or ('range' in x and o['entity'].startswith('ind-')))
        imap.add(key=f"gold:{o['entity']}", source_identifier=o['stix_id'],
                 source_version=FIXTURE['version'],
                 entity_type=e['type'], display_name=o['input']['name'],
                 aliases=e.get('aliases') or [], provenance='gold-graph')
        imap.set_opencti_id(f"gold:{o['entity']}", oid)
        print(f"created {o['entity']} -> {oid}")
    for o in (x for x in ops if x['op'] == 'relate'):
        q = '''mutation R($fromId: StixRef!, $toId: StixRef!, $t: String!) {
          stixCoreRelationshipAdd(input: { fromId: $fromId, toId: $toId, relationship_type: $t }) { id }
        }'''
        data = gql(q, {'fromId': id_by_key[o['from_key']], 'toId': id_by_key[o['to_key']],
                       't': o['input']['relationship_type']})
        print(f"related {o['key']} -> {list(data.values())[0]['id']}")
    imap.save()
    print(f'identity map updated: {len(imap.entries)} entries')


if __name__ == '__main__':
    main()
