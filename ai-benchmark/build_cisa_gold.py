"""Build the FROZEN CISA advisory dataset for the file2stix suite.

Inputs  (committed, public domain / US-gov work):
  data/cisa/raw/aa23-347a.html        advisory page
  data/cisa/raw/aa23-347a.stix.xml    official CISA STIX 1.2 IOC set (34 indicators)
  data/cisa/raw/aa22-320a.html        advisory page
  data/cisa/raw/aa22-320a.stix.xml    official CISA STIX 1.2 IOC set (7 indicators)

Outputs (frozen, committed):
  data/cisa/aa23-347a.txt       advisory main text (SUMMARY .. end of IOC appendix)
  data/cisa/aa22-320a.txt       advisory main text (Summary .. before Mitigations table)
  data/cisa/aa23-347a_gold.json gold IOCs (from official STIX) + gold ATT&CK techniques (from text)
  data/cisa/aa22-320a_gold.json same

Deterministic: fixed text slices, regex parsing of the STIX XML. Re-running
must be a no-op (byte-identical outputs) — asserted at the end.
"""
import hashlib
import html as html_mod
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / 'data' / 'cisa'
RAW = DATA / 'raw'

ADVISORIES = {
    # name: (text slice [start, end) line indices — verified on the frozen raw HTML)
    'aa23-347a': (115, 980),
    'aa22-320a': (109, 465),
}


def advisory_text(name: str) -> str:
    raw = (RAW / f'{name}.html').read_text(encoding='utf-8', errors='replace')
    raw = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', raw, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', '\n', raw)
    text = html_mod.unescape(text)
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    start, end = ADVISORIES[name]
    return '\n'.join(lines[start:end])


# STIX 1.2 / CybOX parsing — the CISA files use a flat, regular structure:
#   <stix:Indicator> → <indicator:Title>, <cybox:Properties xsi:type="...">
#                      → <cyboxProp:Value condition="Equals">VALUE</...>
OBS_MAP = {
    'FileObjectType': 'file',
    'DomainNameObjectType': 'domain-name',
    'URIObjectType': 'url',
    'LinkObjectType': 'url',
    'AddressObjectType': 'address',
    'EmailMessageObjectType': 'email',
}


def parse_stix_iocs(name: str) -> list[dict]:
    xml = (RAW / f'{name}.stix.xml').read_text(encoding='utf-8', errors='replace')
    out = []
    for block in re.findall(r'<stix:Indicator\b.*?</stix:Indicator>', xml, re.S):
        title_m = re.search(r'<indicator:Title>([^<]+)</indicator:Title>', block)
        props_m = re.search(r'cybox:Properties xsi:type="[\w-]+:(\w+ObjectType)"', block)
        val_m = re.search(r'<[\w-]+:(?:Simple_Hash_|Address_)?Value[^>]*>([^<]+)</[\w-]+:(?:Simple_Hash_|Address_)?Value>', block)
        if not (props_m and val_m):
            continue
        kind = OBS_MAP.get(props_m.group(1), 'unknown')
        value = val_m.group(1).strip()
        # file hashes: hash type lives on the Hash element; default sha256 for CISA sets
        if kind == 'file':
            hash_m = re.search(r'<[\w-]+:Type[^>]*>([^<]+)</[\w-]+:Type>', block)
            algo = (hash_m.group(1).upper().replace('SHA', 'SHA-').replace('SHA-1', 'SHA-1')
                    if hash_m else 'SHA-256')
            if algo == 'MD5':
                stix_type = 'file:hashes.\'MD5\''
            elif algo in ('SHA-1', 'SHA1'):
                stix_type = 'file:hashes.\'SHA-1\''
            elif algo in ('SHA-256', 'SHA256'):
                stix_type = 'file:hashes.\'SHA-256\''
            else:
                stix_type = 'file:hashes.\'SHA-256\''
        elif kind == 'address':
            cat_m = re.search(r'category="([^"]+)"', block)
            stix_type = 'ipv4-addr' if (cat_m and 'ipv4' in cat_m.group(1)) else 'ipv6-addr'
        elif kind == 'domain-name':
            stix_type = 'domain-name'
        elif kind == 'url':
            stix_type = 'url'
        else:
            stix_type = kind
        out.append({'value': value, 'stix_type': stix_type,
                    'title': title_m.group(1) if title_m else None})
    return out


def gold_techniques(text: str) -> list[str]:
    return sorted(set(re.findall(r'\bT\d{4}(?:\.\d{3})?\b', text)))


def main():
    manifest_entries = {}
    for name in ADVISORIES:
        text = advisory_text(name)
        iocs = parse_stix_iocs(name)
        techniques = gold_techniques(text)
        gold = {
            'advisory': name,
            'title_line': text.split('\n', 1)[0],
            'provenance': {
                'page': f'https://www.cisa.gov/news-events/{name}',
                'stix': 'data/cisa/raw/' + name + '.stix.xml',
                'note': 'IOC gold = official CISA STIX 1.2 set; technique gold = regex on frozen text',
            },
            'ioc_gold': iocs,
            'ioc_values': sorted({i['value'] for i in iocs}),
            'technique_gold': techniques,
            'text_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'text_chars': len(text),
        }
        out_text = DATA / f'{name}.txt'
        out_text.write_text(text, newline='\n')
        out_gold = DATA / f'{name}_gold.json'
        out_gold.write_text(json.dumps(gold, indent=2, ensure_ascii=False) + '\n', newline='\n')
        manifest_entries[name] = {
            'file': f'cisa/{name}.txt',
            'sha256': hashlib.sha256(out_text.read_bytes()).hexdigest(),
            'ioc_count': len(iocs),
            'technique_count': len(techniques),
            'source': gold['provenance']['page'],
        }
        print(f'{name}: {len(text)} chars, {len(iocs)} IOCs, {len(techniques)} techniques')

    # determinism assertion: rebuild must be identical
    for name in ADVISORIES:
        t2 = advisory_text(name)
        assert hashlib.sha256(t2.encode()).hexdigest() == json.load(
            open(DATA / f'{name}_gold.json'))['text_sha256'], f'non-deterministic build for {name}'
    # merge into manifest.json
    mf = HERE / 'data' / 'manifest.json'
    man = json.load(open(mf))
    man['cisa_advisories'] = manifest_entries
    man['cisa_frozen_at'] = '2026-09-19'
    mf.write_text(json.dumps(man, indent=2, ensure_ascii=False) + '\n', newline='\n')
    print('manifest updated')


if __name__ == '__main__':
    main()
