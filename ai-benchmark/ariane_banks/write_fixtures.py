"""BENCH-SCRATCH write fixtures for the Ariane WRK (write/action) benchmark questions.

Idempotent setup/teardown of disposable objects used exclusively by WRK questions:
  - "BENCH-SCRATCH Report Alpha"          (report)
  - "BENCH-SCRATCH Report Beta"           (report)
  - indicator bench-scratch.example.com   (indicator, STIX pattern)
  - one `related-to` relationship Alpha -> Beta
All carry the `bench-scratch` label. Teardown removes anything matching the reserved
prefixes/names (reports/indicators by name, relationships touching fixture ids).

Usage:
  python3 write_fixtures.py --setup     # create missing fixtures, save ids, update manifest
  python3 write_fixtures.py --teardown  # delete fixtures + touched relationships, verify empty
  python3 write_fixtures.py --status    # show what exists
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
DATA = ROOT / 'data'
FIXTURE_FILE = DATA / 'write_fixtures.json'
MANIFEST = DATA / 'manifest.json'

ADMIN_ENV = Path('/tmp/opencode/opencti-admin.env')
GQL = 'http://localhost:4000/graphql'
ALPHA = 'BENCH-SCRATCH Report Alpha'
BETA = 'BENCH-SCRATCH Report Beta'
DOMAIN = 'bench-scratch.example.com'
LABEL = 'bench-scratch'


def token() -> str:
    for line in ADMIN_ENV.read_text().splitlines():
        if line.startswith('TOKEN='):
            return line.split('=', 1)[1].strip()
    sys.exit('admin token not found')


def gql(query: str, variables: dict | None = None) -> dict:
    req = urllib.request.Request(
        GQL,
        data=json.dumps({'query': query, 'variables': variables or {}}).encode(),
        headers={'Authorization': f'Bearer {token()}', 'Content-Type': 'application/json'},
    )
    r = json.load(urllib.request.urlopen(req, timeout=60))
    if r.get('errors'):
        raise RuntimeError(r['errors'][0].get('message', 'graphql error'))
    return r['data']


def find_by_name(name: str, kind: str) -> dict | None:
    key = 'reports' if kind == 'report' else 'indicators'
    q = f'''{{ {key}(first: 5, filters: {{mode: and, filterGroups: [],
             filters: [{{key: "name", values: ["{name}"]}}]}})
             {{ edges {{ node {{ id name }} }} }} }}'''
    edges = gql(q)[key]['edges']
    return edges[0]['node'] if edges else None


def create(kind: str, name: str) -> dict:
    if kind == 'report':
        d = gql('''mutation($name:String!,$label:[String!]){ reportAdd(input:{
            name:$name, published:"2026-09-22T00:00:00.000Z",
            description:"BENCH-SCRATCH disposable fixture for WRK benchmark questions. Safe to delete.",
            objectLabel:$label }) { id name } }''',
                {'name': name, 'label': [LABEL]})
        return d['reportAdd']
    d = gql('''mutation($name:String!,$pattern:String!,$label:[String!]){ indicatorAdd(input:{
        name:$name, pattern:$pattern, pattern_type:"stix", x_opencti_score:50,
        description:"BENCH-SCRATCH disposable fixture for WRK benchmark questions. Safe to delete.",
        objectLabel:$label }) { id name } }''',
            {'name': name, 'pattern': f"[domain-name:value = '{name}']", 'label': [LABEL]})
    return d['indicatorAdd']


def ensure_relationship(alpha_id: str, beta_id: str, existing: dict) -> dict:
    if existing.get('relationship_id'):
        return {'relationship_id': existing['relationship_id']}
    d = gql('''mutation($from:StixRef!,$to:StixRef!){ stixCoreRelationshipAdd(input:{
        relationship_type:"related-to", fromId:$from, toId:$to,
        description:"BENCH-SCRATCH disposable fixture relationship. Safe to delete." })
        { id } }''', {'from': alpha_id, 'to': beta_id})
    return {'relationship_id': d['stixCoreRelationshipAdd']['id']}


def touched_relationships(fx: dict) -> list[dict]:
    ids = [fx[k] for k in ('alpha_id', 'beta_id', 'indicator_id') if fx.get(k)]
    if not ids:
        return []
    out = []
    for key in ('fromId', 'toId'):
        values = ', '.join(f'"{i}"' for i in ids)
        d2 = gql(f'''{{ stixCoreRelationships(first: 100, filters: {{mode: and, filterGroups: [],
                 filters: [{{key: "{key}", values: [{values}]}}]}})
                 {{ edges {{ node {{ id relationship_type
                   from {{ ... on BasicObject {{ id }} }}
                   to {{ ... on BasicObject {{ id }} }} }} }} }} }}''')
        out += [{'id': e['node']['id'], 'from': e['node']['from']['id'],
                 'to': e['node']['to']['id'], 'type': e['node']['relationship_type']}
                for e in d2['stixCoreRelationships']['edges']]
    seen, uniq = set(), []
    for r in out:
        if r['id'] not in seen:
            seen.add(r['id'])
            uniq.append(r)
    return uniq


def delete_objects(ids: list[str]) -> None:
    if not ids:
        return
    values = ', '.join(f'"{i}"' for i in ids)
    gql(f'mutation {{ stixDomainObjectsDelete(id: [{values}]) }}')
    print(f'deleted objects: {len(ids)}')


def delete_relationships(rels: list[dict]) -> None:
    for r in rels:
        gql('''mutation($f:StixRef!,$t:StixRef!,$type:String!){
            stixCoreRelationshipDelete(fromId:$f, toId:$t, relationship_type:$type) }''',
            {'f': r['from'], 't': r['to'], 'type': r['type']})
    if rels:
        print(f'deleted relationships: {len(rels)}')


def load() -> dict:
    if FIXTURE_FILE.exists():
        return json.load(open(FIXTURE_FILE))
    return {}


def save(fx: dict) -> None:
    DATA.mkdir(exist_ok=True)
    json.dump(fx, open(FIXTURE_FILE, 'w'), indent=1)


def setup() -> None:
    fx = load()
    for key, kind, name in (('alpha_id', 'report', ALPHA), ('beta_id', 'report', BETA),
                            ('indicator_id', 'indicator', DOMAIN)):
        if fx.get(key):
            continue
        found = find_by_name(name, kind)
        fx[key] = found['id'] if found else create(kind, name)['id']
        print(f'{kind}: {name} -> {fx[key]}')
    rel = ensure_relationship(fx['alpha_id'], fx['beta_id'], fx)
    fx.update(rel)
    print('relationship:', fx.get('relationship_id'))
    save(fx)
    if MANIFEST.exists():
        m = json.load(open(MANIFEST))
        m['write_fixtures'] = {
            'purpose': 'disposable BENCH-SCRATCH objects for WRK benchmark questions',
            'file': FIXTURE_FILE.name,
            'names': [ALPHA, BETA, DOMAIN],
            'label': LABEL,
        }
        json.dump(m, open(MANIFEST, 'w'), indent=2)
    print('setup complete')


def teardown() -> None:
    fx = load()
    delete_relationships(touched_relationships(fx))
    ids = [fx[k] for k in ('alpha_id', 'beta_id', 'indicator_id') if fx.get(k)]
    delete_objects(ids)
    # sweep by name in case ids were stale
    for kind, name in (('report', ALPHA), ('report', BETA), ('indicator', DOMAIN)):
        found = find_by_name(name, kind)
        if found:
            delete_objects([found['id']])
    FIXTURE_FILE.unlink(missing_ok=True)
    left = [n for n in (ALPHA, BETA, DOMAIN) if find_by_name(n, 'report' if 'Report' in n else 'indicator')]
    assert not left, f'leftover fixtures: {left}'
    print('teardown complete, no leftovers')


def status() -> None:
    fx = load()
    print('fixture file:', fx if fx else 'absent')
    for kind, name in (('report', ALPHA), ('report', BETA), ('indicator', DOMAIN)):
        print(f'{kind} {name!r}:', (find_by_name(name, kind) or {'id': 'MISSING'})['id'])


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--setup', action='store_true')
    g.add_argument('--teardown', action='store_true')
    g.add_argument('--status', action='store_true')
    args = ap.parse_args()
    if args.setup:
        setup()
    elif args.teardown:
        teardown()
    else:
        status()
