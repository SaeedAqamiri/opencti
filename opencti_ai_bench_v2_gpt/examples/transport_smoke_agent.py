"""Deterministic C01 transport smoke test. NOT a general agent or model baseline."""
import json,sys
req=json.loads(sys.stdin.readline()); cid=req['case']['id']
if cid!='C01':
    print('This example handles C01 only; no score is implied for other cases.',file=sys.stderr); raise SystemExit(2)
counter=0
def call(tool,args):
    global counter
    counter+=1; ident=str(counter)
    print(json.dumps({'type':'tool_call','id':ident,'tool':tool,'args':args}),flush=True)
    r=json.loads(sys.stdin.readline())
    if r.get('id')!=ident or not r['result']['ok']: raise RuntimeError('Tool failed')
    return r['result']
r=call('search_entities',{'query':'TEST Aster','entity_type':'intrusion-set'})
key=r['items'][0]['key']; cursor=0; records={}; keys=[]
while True:
    r=call('get_neighbors',{'key':key,'predicate':'uses','target_type':'tool','direction':'out','active_only':True,'cursor':cursor})
    keys += [x['key'] for x in r['items']]
    records.update({x['key']:x for x in r['records']})
    if not r['has_next_page']: break
    cursor=r['next_cursor']
claims=[{'kind':'relation','subject':r['source'],'predicate':r['predicate'],'object':r['target'],'evidence_ids':[k]} for k,r in records.items() if 'predicate' in r]
answer={'case_id':cid,'answer_state':'ANSWERED','complete':True,'answer':'','entity_keys':sorted(set(keys)),'values':{},'claims':claims,'citations':sorted(records)}
print(json.dumps({'type':'final','answer':answer}),flush=True)