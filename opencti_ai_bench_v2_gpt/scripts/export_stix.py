"""Export synthetic fixture content as STIX 2.1. ACL and fault tests stay in harness.
This is not a claim of successful import into any particular OpenCTI version.
"""
import hashlib,json,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
g=json.loads((ROOT/'data/gold_graph.json').read_text(encoding='utf-8'))
def sid(t,k):
    return t+'--'+str(uuid.UUID(bytes=hashlib.sha256(('ctibench-v2:'+k).encode()).digest()[:16],version=4))
ts='2026-01-01T00:00:00.000Z'
ids={n['key']:sid(n['type'],n['key']) for n in g['nodes']}
ids.update({e['key']:sid('relationship',e['key']) for e in g['edges']})
ids.update({d['key']:sid('report',d['key']) for d in g['documents']})
identity=sid('identity','publisher'); public=sid('marking-definition','public'); restricted=sid('marking-definition','restricted')
objs=[{'type':'identity','spec_version':'2.1','id':identity,'created':ts,'modified':ts,'name':'Synthetic OpenCTI AI Benchmark v2 - NOT REAL THREAT INTELLIGENCE','identity_class':'organization'}]
for k,label in [(public,'PUBLIC SYNTHETIC FIXTURE - NOT REAL THREAT INTELLIGENCE'),(restricted,'RESTRICTED SYNTHETIC FIXTURE - configure ACL before testing')]:
    objs.append({'type':'marking-definition','spec_version':'2.1','id':k,'created':ts,'definition_type':'statement','definition':{'statement':label}})
for n in g['nodes']:
    o={'type':n['type'],'spec_version':'2.1','id':ids[n['key']],'x_benchmark_key':n['key'],'x_benchmark_synthetic':True,'object_marking_refs':[restricted if n['access']=='restricted' else public]}
    if n['type'] in ('domain-name','ipv4-addr'):
        o['value']=n['value']
    elif n['type']=='file': o.update(name=n['name'],hashes=n['hashes'])
    else:
        o.update(created=ts,modified=ts,created_by_ref=identity,name=n['name'],description='Synthetic fixture only. See x_benchmark_key and the benchmark graph for controlled semantics.',external_references=[{'source_name':'opencti-ai-bench-synthetic','external_id':n['key']}])
        if n.get('aliases'): o['aliases']=n['aliases']
        if n['type']=='malware': o['is_family']=True
        if n['type']=='indicator':
            o.update(pattern=n['pattern'],pattern_type='stix',pattern_version='2.1',valid_from=n['valid_from'])
            if 'valid_until' in n: o['valid_until']=n['valid_until']
        if n['type']=='campaign': o['first_seen']=n['first_seen']
        if n.get('revoked'): o['revoked']=True
        if n.get('deprecated'): o['x_benchmark_deprecated']=True
    objs.append(o)
for e in g['edges']:
    objs.append({'type':'relationship','spec_version':'2.1','id':ids[e['key']],'created':ts,'modified':ts,'created_by_ref':identity,'relationship_type':e['predicate'],'source_ref':ids[e['source']],'target_ref':ids[e['target']],'object_marking_refs':[restricted if e['access']=='restricted' else public],'x_benchmark_key':e['key'],'x_benchmark_origin':e['origin'],'x_benchmark_source_document':ids[e['source_document']],'description':'Synthetic evidence; origin='+e['origin']})
for d in g['documents']:
    related=[ids[e['key']] for e in g['edges'] if e['source_document']==d['key']]
    refs=set(related)
    for e in g['edges']:
        if e['source_document']==d['key']: refs.update([ids[e['source']],ids[e['target']]])
    objs.append({'type':'report','spec_version':'2.1','id':ids[d['key']],'created':ts,'modified':d['modified'],'created_by_ref':identity,'name':d['title'],'description':d['text'],'published':d['modified'],'report_types':['threat-report'],'object_refs':sorted(refs) or [identity],'object_marking_refs':[restricted if d['access']=='restricted' else public],'x_benchmark_key':d['key'],'x_benchmark_synthetic':True})
valid_ids={o['id'] for o in objs}
for o in objs:
    for field in ('source_ref','target_ref','created_by_ref'):
        if field in o: assert o[field] in valid_ids
    for field in ('object_refs','object_marking_refs'):
        for ref in o.get(field,[]): assert ref in valid_ids
bundle={'type':'bundle','id':sid('bundle','bundle-v2'),'objects':objs}
(ROOT/'data/synthetic_bundle.stix2.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(ROOT/'data/source_identity_map.json').write_text(json.dumps({'status':'SOURCE_IDS_ONLY_NOT_OPENCTI_INTERNAL_IDS','mapping':ids},indent=2)+'\n')
print('Exported',len(objs),'STIX objects; reference integrity checked.')