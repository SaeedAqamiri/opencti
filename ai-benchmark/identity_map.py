"""Benchmark identity map (grader v2).

The platform regenerates canonical STIX ids on import, so name-only matching
loses distinctions (66 golden ids collapse to 64 unique names). This module
gives every benchmark entity a stable `benchmark_entity_key` and records:

  benchmark_entity_key : stable slug used by graders
  source_identifier    : id in the frozen source dataset (STIX id / ATT&CK ext id / OTX type+value)
  source_version       : frozen dataset version
  opencti_identifier   : id assigned by the platform at import time (if known)
  entity_type          : STIX-ish type
  display_name         : human name
  aliases              : known aliases (resolved to the same key)

Provenance of every entry is recorded so hand-built gold-graph relations,
source-native relations and converter-created relations stay distinguishable.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def slug(s: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', (s or '').lower()).strip('-')
    return s or 'unnamed'


class IdentityMap:
    FILE = Path(__file__).parent / 'agent_bench' / 'identity_map.json'

    def __init__(self, entries: list[dict] | None = None):
        self.entries: list[dict] = entries or []

    # ── persistence ──────────────────────────────────────────────────────
    @classmethod
    def load(cls, path: Path | None = None) -> 'IdentityMap':
        p = path or cls.FILE
        if not p.exists():
            return cls()
        return cls(json.load(open(p)))

    def save(self, path: Path | None = None):
        p = path or self.FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.entries, indent=2, ensure_ascii=False))

    # ── registration ─────────────────────────────────────────────────────
    def add(self, *, key: str, source_identifier: str, source_version: str,
            entity_type: str, display_name: str, opencti_identifier: str = '',
            aliases: list[str] | None = None, provenance: str = 'source-native') -> str:
        bkey = key or slug(f'{entity_type}:{display_name}')
        entry = {
            'benchmark_entity_key': bkey,
            'source_identifier': source_identifier,
            'source_version': source_version,
            'opencti_identifier': opencti_identifier,
            'entity_type': entity_type,
            'display_name': display_name,
            'aliases': aliases or [],
            'provenance': provenance,   # source-native | converter | gold-graph | manual
        }
        for i, e in enumerate(self.entries):
            if e['benchmark_entity_key'] == bkey:
                self.entries[i] = {**e, **{k: v for k, v in entry.items() if v}}
                return bkey
        self.entries.append(entry)
        return bkey

    def set_opencti_id(self, key: str, opencti_id: str):
        for e in self.entries:
            if e['benchmark_entity_key'] == key:
                e['opencti_identifier'] = opencti_id
                return

    # ── resolution ───────────────────────────────────────────────────────
    def _index(self) -> dict[str, str]:
        idx: dict[str, str] = {}
        for e in self.entries:
            names = [e['display_name'], e['source_identifier'], e['benchmark_entity_key'], *e.get('aliases', [])]
            for n in names:
                if n:
                    idx[n.strip().lower()] = e['benchmark_entity_key']
                    idx[n.strip().lower().replace('_', ' ')] = e['benchmark_entity_key']
        return idx

    def resolve(self, name: str) -> str | None:
        """Resolve a display name / alias / id to the canonical benchmark_entity_key."""
        if not name:
            return None
        return self._index().get(str(name).strip().lower())

    def by_key(self, key: str) -> dict | None:
        return next((e for e in self.entries if e['benchmark_entity_key'] == key), None)

    def by_opencti_id(self, oid: str) -> dict | None:
        return next((e for e in self.entries if e.get('opencti_identifier') == oid), None)
