"""Build a FROZEN AlienVault OTX snapshot tied to entities already in our graph.

Bounded, deterministic ingestion:
  for each target name (intrusion sets / malware already imported from ATT&CK):
    search pulses -> pick the N most recent -> fetch up to M indicators
  -> emit a STIX 2.1 bundle (reports + indicators + observables + related-to links)
  -> freeze to data/otx-snapshot-<date>.json + manifest (sha256, counts)

The OTX API key is read from OTX_API_KEY env or /tmp/opencode/otx.env — never committed.
Usage: python3 fetch_otx_snapshot.py [--pulses-per-target 2] [--indicators-per-pulse 50]
"""
import argparse
import hashlib
import uuid as uuid_mod
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).parent
DATA = HERE / 'data'
ATTACK_FILE = DATA / 'enterprise-attack-2026-09-15.json'
API = 'https://otx.alienvault.com/api/v1'

# deterministic name -> aliases (lowercase substrings matched against pulse adversary/tags/title)
TARGETS = {
    'APT28': ['apt28', 'sofacy', 'fancy bear', 'pawn storm'],
    'APT29': ['apt29', 'cozy bear', 'the dukes'],
    'Kimsuky': ['kimsuky'],
    'Sandworm': ['sandworm', 'voodoo bear'],
    'Lazarus': ['lazarus', 'hidden cobra'],
    'Zebrocy': ['zebrocy'],
}

TYPE_MAP = {  # OTX indicator type -> (STIX SCO type, pattern object path)
    'IPv4': ('ipv4-addr', "[ipv4-addr:value = '{v}']"),
    'domain': ('domain-name', "[domain-name:value = '{v}']"),
    'hostname': ('domain-name', "[domain-name:value = '{v}']"),
    'URL': ('url', "[url:value = '{v}']"),
    'FileHash-SHA256': ('file', "[file:hashes.'SHA-256' = '{v}']"),
    'FileHash-MD5': ('file', "[file:hashes.'MD5' = '{v}']"),
    'FileHash-SHA1': ('file', "[file:hashes.'SHA-1' = '{v}']"),
    'email': ('email-addr', "[email-addr:value = '{v}']"),
}


def otx_key() -> str:
    key = os.environ.get('OTX_API_KEY')
    if key:
        return key
    env = Path('/tmp/opencode/otx.env')
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith('OTX_API_KEY='):
                return line.split('=', 1)[1].strip()
    raise SystemExit('OTX_API_KEY missing')


S = requests.Session()
S.headers['X-OTX-API-KEY'] = otx_key()


def get(url: str, **kw) -> dict:
    for attempt in range(3):
        try:
            r = S.get(url, timeout=60, **kw)
            r.raise_for_status()
            return r.json()
        except Exception:  # noqa: BLE001
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    return {}


def stix_ts(s: str | None) -> str:
    """Normalize OTX timestamps ('2016-09-26T18:17:45') to STIX ('...T...SS.sssZ')."""
    if not s:
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    s = s.strip()
    if s.endswith('Z'):
        return s
    if '.' not in s:
        s += '.000'
    return s + 'Z'


DET_NS = uuid_mod.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')


def det_id(prefix: str, *parts: str) -> str:
    return f'{prefix}--{uuid_mod.uuid5(DET_NS, ":".join(parts))}'


def sco_object(sco_type: str, value: str, stix_id: str, created: str) -> dict:
    base = {'type': sco_type, 'spec_version': '2.1', 'id': stix_id, 'value': value}
    if sco_type == 'file':
        base.pop('value')
        alg = 'SHA-256' if len(value) == 64 else 'SHA-1' if len(value) == 40 else 'MD5'
        base['hashes'] = {alg: value}
    if sco_type in ('ipv4-addr', 'domain-name', 'url', 'email-addr'):
        base['value'] = value
    base['created'] = created
    base['modified'] = created
    return base


def make_sco(ioc_type: str, value: str) -> dict | None:
    mapped = TYPE_MAP.get(ioc_type)
    if not mapped:
        return None
    sco_type, pattern_tpl = mapped
    created = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    stix_id = det_id(sco_type, ioc_type, value.lower())
    obj = sco_object(sco_type, value, stix_id, created)
    pattern = pattern_tpl.format(v=value.replace("'", '\\\''))
    return {'sco': obj, 'pattern': pattern}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--pulses-per-target', type=int, default=2)
    ap.add_argument('--indicators-per-pulse', type=int, default=50)
    args = ap.parse_args()

    attack = json.load(open(ATTACK_FILE))
    is_ids = {}
    for o in attack['objects']:
        if o['type'] == 'intrusion-set' and o.get('name') in TARGETS:
            is_ids[o['name']] = o['id']

    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    objects: list[dict] = []
    seen_pulse_ids: set[str] = set()
    stats: Counter = Counter()

    for target, aliases in TARGETS.items():
        q = ' OR '.join(aliases)
        print(f'[{target}] searching pulses: {q}', flush=True)
        res = get(f'{API}/search/pulses', params={'q': q, 'limit': 10}).get('results', [])
        picked = 0
        for p in res:
            if picked >= args.pulses_per_target or p['id'] in seen_pulse_ids:
                continue
            seen_pulse_ids.add(p['id'])
            blob = ' '.join([p.get('name', ''), ' '.join(p.get('tags') or []), p.get('adversary') or '']).lower()
            linked_is = next((t for t, als in TARGETS.items() if any(a in blob for a in als)), None)
            ind_res = get(f"{API}/pulses/{p['id']}/indicators", params={'limit': args.indicators_per_pulse})
            refs = []
            for ioc in ind_res.get('results', []):
                sco = make_sco(ioc.get('type', ''), ioc.get('indicator', ''))
                if not sco:
                    continue
                ind_id = det_id('indicator', ioc.get('type',''), ioc.get('indicator','').lower())
                created = ioc.get('created') or now
                indicator = {
                    'type': 'indicator', 'spec_version': '2.1', 'id': ind_id,
                    'created': stix_ts(created), 'modified': stix_ts(created),
                    'name': ioc.get('indicator', ''),
                    'pattern': sco['pattern'], 'pattern_type': 'stix',
                    'valid_from': stix_ts(created),
                    'labels': (p.get('tags') or [])[:8],
                    'description': ioc.get('description') or f"IOC from OTX pulse {p['name']}",
                    'x_opencti_score': 50,
                }
                objects.append(indicator)
                objects.append(sco['sco'])
                refs.extend([ind_id, sco['sco']['id']])
                stats['indicators'] += 1
                if linked_is and linked_is in is_ids:
                    objects.append({
                        'type': 'relationship', 'spec_version': '2.1',
                        'id': det_id('relationship', ind_id, is_ids[linked_is]),
                        'created': now, 'modified': now,
                        'relationship_type': 'related-to',
                        'source_ref': ind_id, 'target_ref': is_ids[linked_is],
                    })
                    stats['links_to_att&ck'] += 1
            if refs:
                objects.append({
                    'type': 'report', 'spec_version': '2.1',
                    'id': f"report--{__import__('uuid').uuid4()}",
                    'created': stix_ts(p.get('created')), 'modified': stix_ts(p.get('modified')),
                    'name': f"[OTX] {p.get('name', p['id'])}"[:250],
                    'description': (p.get('description') or '')[:5000],
                    'published': stix_ts(p.get('created')),
                    'labels': list({*(p.get('tags') or []), *([p['adversary']] if p.get('adversary') else [])})[:10],
                    'object_refs': refs,
                    'external_references': [{'source_name': 'AlienVault OTX', 'url': f"https://otx.alienvault.com/pulse/{p['id']}/"}],
                })
                stats['reports'] += 1
            picked += 1
            time.sleep(1)

    bundle = {'type': 'bundle', 'id': f"bundle--{__import__('uuid').uuid4()}", 'objects': objects}
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    out = DATA / f'otx-snapshot-{stamp}.json'
    json.dump(bundle, open(out, 'w'))
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    manifest = json.load(open(DATA / 'manifest.json'))
    manifest['otx_snapshot'] = {
        'file': out.name, 'frozen_at': stamp, 'sha256': sha,
        'targets': TARGETS, 'pulses_per_target': args.pulses_per_target,
        'indicators_per_pulse': args.indicators_per_pulse,
        'counts': dict(stats),
    }
    json.dump(manifest, open(DATA / 'manifest.json', 'w'), indent=2)
    print('DONE', out.name, '|', dict(stats), '| sha256[:16]=', sha[:16])


if __name__ == '__main__':
    main()
