"""Dataset access and narrowly typed, read-only fixture queries (Python stdlib)."""
from __future__ import annotations
import copy, hashlib, json
from datetime import datetime
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[1]
def load_json(path: str|Path) -> Any:
    return json.loads(Path(path).read_text(encoding='utf-8'))
def load_jsonl(path: str|Path) -> list[dict]:
    return [json.loads(s) for s in Path(path).read_text(encoding='utf-8').splitlines() if s.strip()]
def cases() -> dict[str,dict]: return {x['id']:x for x in load_jsonl(ROOT/'cases/public_cases.jsonl')}
def goldens() -> dict[str,dict]: return {x['case_id']:x for x in load_jsonl(ROOT/'evaluator_private/goldens.jsonl')}
def digest(value: Any) -> str:
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(raw).hexdigest()
class ContractError(ValueError): pass

def shape(obj: Any, required: dict[str,type], optional: dict[str,type]|None=None) -> None:
    """Reject unknown fields and Python bool-as-int coercion."""
    if type(obj) is not dict: raise ContractError('Expected an object')
    optional=optional or {}; allowed={**required,**optional}
    if set(obj)-set(allowed): raise ContractError('Unexpected fields: '+','.join(sorted(set(obj)-set(allowed))))
    if set(required)-set(obj): raise ContractError('Missing fields: '+','.join(sorted(set(required)-set(obj))))
    for k,v in obj.items():
        if type(v) is not allowed[k]: raise ContractError(f'Invalid type for {k}')

def validate_query(q: dict) -> None:
    if type(q) is not dict or type(q.get('op')) is not str: raise ContractError('Query needs op')
    ops={
      'search':({'op':str,'name':str},{'entity_type':str}),
      'neighbors':({'op':str,'key':str,'predicate':str,'direction':str,'target_type':str,'active_only':bool},{}),
      'intersection':({'op':str,'left':str,'right':str,'target_type':str},{}),
      'shared_threshold':({'op':str,'key':str,'minimum':int},{}),
      'mitigations_for':({'op':str,'key':str},{}),
      'campaigns_between':({'op':str,'start':str,'end':str},{}),
      'valid_indicators':({'op':str,'as_of':str},{}),
    }
    if q['op'] not in ops: raise ContractError('Unsupported query op')
    shape(q,*ops[q['op']])
    if q['op']=='neighbors' and q['direction'] not in ('in','out'): raise ContractError('Bad direction')
    if q['op']=='shared_threshold' and not 1<=q['minimum']<=1000: raise ContractError('Bad minimum')
    if q['op']=='campaigns_between':
        from datetime import datetime
        try:
            a=datetime.fromisoformat(q['start'].replace('Z','+00:00')); b=datetime.fromisoformat(q['end'].replace('Z','+00:00'))
            if a.tzinfo is None or b.tzinfo is None or a>=b: raise ValueError()
        except ValueError as exc: raise ContractError('Invalid UTC date range') from exc
    if q['op']=='valid_indicators':
        from datetime import datetime
        try:
            if datetime.fromisoformat(q['as_of'].replace('Z','+00:00')).tzinfo is None: raise ValueError()
        except ValueError as exc: raise ContractError('Invalid timestamp') from exc

class Graph:
    def __init__(self, data: dict|None=None, principal: str='public'):
        self.data=copy.deepcopy(data if data is not None else load_json(ROOT/'data/gold_graph.json'))
        if principal not in self.data['principals']: raise ContractError('Unknown principal')
        self.principal=principal; access=set(self.data['principals'][principal])
        self.nodes={x['key']:x for x in self.data['nodes'] if x['access'] in access}
        self.documents={x['key']:x for x in self.data['documents'] if x['access'] in access}
        self.edges={x['key']:x for x in self.data['edges'] if x['access'] in access and x['source'] in self.nodes and x['target'] in self.nodes and x['source_document'] in self.documents}
        self.records={**self.nodes,**self.edges,**self.documents}
        for k,v in self.data['activity'].items():
            if k in self.nodes: self.records['activity:'+k]={'key':'activity:'+k,'entity':k,'bins':v}
        for e in self.data['history']:
            if e['entity'] in self.nodes: self.records[e['id']]={'key':e['id'],**e}
    def search(self,name: str,entity_type: str|None=None) -> list[str]:
        needle=name.casefold().strip()
        return sorted(k for k,n in self.nodes.items() if (entity_type is None or n['type']==entity_type) and any(needle in x.casefold() for x in [n['name']]+n.get('aliases',[])))
    def adjacent(self,key: str,predicate: str='uses',target_type: str|None=None,direction: str='out',active_only: bool=True) -> tuple[list[str],list[str]]:
        out=set(); evidence=[]
        for k,e in self.edges.items():
            if e['predicate']!=predicate: continue
            a,b=(e['source'],e['target']) if direction=='out' else (e['target'],e['source'])
            if a!=key: continue
            n=self.nodes[b]
            if target_type is not None and n['type']!=target_type: continue
            if active_only and not n['active']: continue
            out.add(b); evidence.append(k)
        return sorted(out),sorted(evidence)
    def query(self,q: dict) -> tuple[list[str],list[str]]:
        validate_query(q); op=q['op']; ev=[]
        if op=='search': ids=self.search(q['name'],q.get('entity_type'))
        elif op=='neighbors': ids,ev=self.adjacent(q['key'],q['predicate'],q['target_type'],q['direction'],q['active_only'])
        elif op=='intersection':
            a,ea=self.adjacent(q['left'],target_type=q['target_type']); b,eb=self.adjacent(q['right'],target_type=q['target_type']); ids=sorted(set(a)&set(b)); ev=[k for k in ea+eb if self.edges[k]['target'] in ids]
        elif op=='shared_threshold':
            base,ebase=self.adjacent(q['key'],target_type='attack-pattern'); ids=[]
            for k,n in self.nodes.items():
                if n['type']!='intrusion-set' or k==q['key']: continue
                other,eo=self.adjacent(k,target_type='attack-pattern'); shared=set(base)&set(other)
                if len(shared)>=q['minimum']:
                    ids.append(k); ev.extend(e for e in ebase+eo if self.edges[e]['target'] in shared)
        elif op=='mitigations_for':
            pats,ep=self.adjacent(q['key'],target_type='attack-pattern'); ids=[]; ev+=ep
            for p in pats:
                coas,ec=self.adjacent(p,'mitigates','course-of-action','in'); ids.extend(coas); ev+=ec
        elif op=='campaigns_between':
            ids=[k for k,n in self.nodes.items() if n['type']=='campaign' and datetime.fromisoformat(q['start'].replace('Z','+00:00'))<=datetime.fromisoformat(n['first_seen'].replace('Z','+00:00'))<datetime.fromisoformat(q['end'].replace('Z','+00:00'))]
        elif op=='valid_indicators':
            ids=[k for k,n in self.nodes.items() if n['type']=='indicator' and 'valid_until' in n and datetime.fromisoformat(n['valid_from'].replace('Z','+00:00'))<=datetime.fromisoformat(q['as_of'].replace('Z','+00:00'))<datetime.fromisoformat(n['valid_until'].replace('Z','+00:00'))]
        else: raise ContractError('Unreachable query')
        return sorted(set(ids)),sorted(set(ev))
    def context(self,spec: dict|None) -> dict:
        spec=spec or {}; rec=[]
        for k in spec.get('entities',[])+spec.get('documents',[]):
            if k in self.records: rec.append(copy.deepcopy(self.records[k]))
        entity_keys=set(spec.get('entities',[]))
        for e in self.edges.values():
            if e['source'] in entity_keys and e['target'] in entity_keys: rec.append(copy.deepcopy(e))
        for k in spec.get('activity',[]):
            if 'activity:'+k in self.records: rec.append(copy.deepcopy(self.records['activity:'+k]))
        if spec.get('history'): rec.extend(copy.deepcopy(v) for k,v in self.records.items() if k.startswith('event_'))
        return {'records':rec,'messages':copy.deepcopy(spec.get('messages',[]))}