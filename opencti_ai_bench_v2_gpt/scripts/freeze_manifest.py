"""Freeze artifact bytes AFTER review. Do not use this to conceal import failures."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
skip={'manifest.sha256.json'}
manifest={}
for p in sorted(ROOT.rglob('*')):
    if not p.is_file(): continue
    rel=p.relative_to(ROOT)
    if any(x in ('__pycache__','runs','reports','.git') for x in rel.parts): continue
    if p.name in skip or p.name=='.audit-key' or p.suffix in ('.pyc','.key'): continue
    manifest[rel.as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
(ROOT/'manifest.sha256.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Frozen',len(manifest),'file digests')
