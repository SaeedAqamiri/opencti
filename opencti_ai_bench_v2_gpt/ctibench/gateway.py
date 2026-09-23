"""Evaluator-owned tool boundary. It records actual fixture operations, not agent claims."""
from __future__ import annotations
import copy, json, time
from .store import Graph, ContractError, shape, digest
TOOL_SCHEMAS={
 'search_entities': ({'query':str},{'entity_type':str,'cursor':int,'limit':int}),
 'get_entity': ({'key':str},{}),
 'get_neighbors': ({'key':str},{'predicate':str,'target_type':str,'direction':str,'active_only':bool,'cursor':int,'limit':int}),
 'get_document': ({'key':str},{}),
 'get_activity': ({'key':str},{}),
 'get_history': ({},{'key':str}),
 'query_graph': ({'query':dict},{'cursor':int,'limit':int}),
}
WRITE_TOOLS={'create_report','create_relationship','add_to_container','delete_entity','update_entity'}
class Gateway:
    def __init__(self,case:dict,faults:list|None=None,graph:Graph|None=None):
        self.case=case; self.graph=graph or Graph(principal=case['principal']); self.events=[]
        self.faults=faults or []; self.invocations={}; self.started=time.monotonic(); self.bytes_out=0
        self.initial_context=self.graph.context(case.get('context'))
        self.before=digest(self.graph.data)
    def error(self,code:str,message:str,partial:dict|None=None):
        out={'ok':False,'error':{'code':code,'message':message},'records':[],'complete':False}
        if partial is not None: out.update(partial); out['ok']=False; out['complete']=False
        return out
    def page(self,ids:list[str],evidence:list[str],cursor:int=0,limit:int=7):
        cap=min(limit,7); end=min(cursor+cap,len(ids)); page_ids=ids[cursor:end]
        # Return support edges touching the current page. For multi-hop queries, retain
        # support edges as well, bounded by the evaluator's byte caps.
        records=[copy.deepcopy(self.graph.records[k]) for k in page_ids if k in self.graph.records]
        for k in sorted(set(evidence)):
            if k in self.graph.records: records.append(copy.deepcopy(self.graph.records[k]))
        return {'ok':True,'items':[{'key':k,'name':self.graph.nodes[k]['name'],'type':self.graph.nodes[k]['type']} for k in page_ids], 'records':records,'returned_count':len(page_ids),'total_count':len(ids),'next_cursor':end if end<len(ids) else None,'has_next_page':end<len(ids),'complete':end==len(ids)}
    def call(self,tool:str,args:dict,*,actor:str='candidate') -> dict:
        begin=time.monotonic(); call_n=len(self.events)+1
        self.invocations[tool]=self.invocations.get(tool,0)+1
        is_write=tool in WRITE_TOOLS; code=None
        if is_write: out=self.error('WRITE_BLOCKED','This benchmark run is read-only.')
        elif tool not in self.case['allowed_tools']: out=self.error('TOOL_DENIED','Tool not allowed in this run.')
        elif actor=='candidate' and sum(e.get('actor','candidate')=='candidate' for e in self.events)>=self.case['budget']['max_tool_calls']: out=self.error('BUDGET_EXCEEDED','Tool-call budget exhausted.')
        elif begin-self.started>self.case['budget']['wall_seconds']: out=self.error('TIME_BUDGET','Run time budget exhausted.')
        elif tool not in TOOL_SCHEMAS: out=self.error('UNKNOWN_TOOL','Unsupported tool.')
        else:
            try:
                shape(args,*TOOL_SCHEMAS[tool])
                if 'cursor' in args and args['cursor']<0: raise ContractError('Negative cursor')
                if 'limit' in args and not 1<=args['limit']<=100: raise ContractError('Limit must be 1..100')
                if args.get('direction','out') not in ('in','out'): raise ContractError('Bad direction')
                fault=next((f for f in self.faults if f['tool']==tool),None)
                if fault and (fault['mode']=='timeout_always' or fault['mode']=='timeout_once' and self.invocations[tool]==1):
                    out=self.error('TIMEOUT','Injected deterministic backend timeout; no actual 15-second delay.')
                elif fault and fault['mode']=='schema_always': out=self.error('SCHEMA_MISMATCH','Injected incompatible backend contract.')
                else:
                    out=self._execute(tool,args)
                    if fault and fault['mode']=='partial_always':
                        out['items']=out.get('items',[])[:1]
                        keep={x['key'] for x in out['items']}
                        out['records']=[x for x in out.get('records',[]) if x.get('key') in keep or ('predicate' in x and (x.get('source') in keep or x.get('target') in keep))]
                        out['returned_count']=len(out['items']); out['has_next_page']=True; out['next_cursor']=None
                        out=self.error('PARTIAL_DATA','Injected partial GraphQL-like response.',out)
            except (ContractError,KeyError,TypeError,ValueError) as exc: out=self.error('INVALID_ARGUMENTS',str(exc))
        raw=json.dumps(out,ensure_ascii=False).encode()
        if len(raw)>self.case['budget']['max_response_bytes'] or self.bytes_out+len(raw)>self.case['budget']['max_total_tool_bytes']:
            out=self.error('OUTPUT_BUDGET','Tool response exceeds byte budget.'); raw=json.dumps(out).encode()
        self.bytes_out+=len(raw)
        event={'actor':actor,'event_id':f'call-{call_n:04d}','tool':tool,'args':copy.deepcopy(args),'result':copy.deepcopy(out),'duration_ms':round((time.monotonic()-begin)*1000,3),'output_bytes':len(raw),'fixture_operations':1,'backend_requests':0,'write_attempted':is_write,'write_executed':False}
        self.events.append(event)
        return out
    def _execute(self,tool,args):
        if tool=='search_entities':
            ids=self.graph.search(args['query'],args.get('entity_type')); return self.page(ids,[],args.get('cursor',0),args.get('limit',7))
        if tool=='get_neighbors':
            if args['key'] not in self.graph.nodes: return self.error('NOT_FOUND_OR_DENIED','No visible object for this key.')
            ids,edges=self.graph.adjacent(args['key'],args.get('predicate','uses'),args.get('target_type'),args.get('direction','out'),args.get('active_only',True))
            page_ids=ids[args.get('cursor',0):args.get('cursor',0)+min(args.get('limit',7),7)]
            edges=[k for k in edges if self.graph.edges[k]['source'] in page_ids or self.graph.edges[k]['target'] in page_ids]
            return self.page(ids,edges,args.get('cursor',0),args.get('limit',7))
        if tool=='query_graph':
            ids,edges=self.graph.query(args['query']); return self.page(ids,edges,args.get('cursor',0),args.get('limit',7))
        if tool=='get_entity':
            if args['key'] not in self.graph.nodes: return self.error('NOT_FOUND_OR_DENIED','No visible object for this key.')
            return {'ok':True,'records':[copy.deepcopy(self.graph.nodes[args['key']])],'complete':True}
        if tool=='get_document':
            key=args['key']
            if key not in self.graph.documents:
                # Accept an exact visible title as a convenience, not an arbitrary URL.
                key=next((k for k,d in self.graph.documents.items() if d['title']==key),'')
            if key not in self.graph.documents: return self.error('NOT_FOUND_OR_DENIED','No visible document for this key.')
            return {'ok':True,'records':[copy.deepcopy(self.graph.documents[key])],'complete':True}
        if tool=='get_activity':
            k='activity:'+args['key']
            if k not in self.graph.records: return self.error('NOT_FOUND_OR_DENIED','No visible series.')
            return {'ok':True,'records':[copy.deepcopy(self.graph.records[k])],'complete':True}
        if tool=='get_history':
            rows=[copy.deepcopy(x) for k,x in self.graph.records.items() if k.startswith('event_') and (args.get('key') is None or x['entity']==args['key'])]
            return {'ok':True,'records':rows,'complete':True}
        raise ContractError('Unsupported tool')
    def audit(self,run_id:str,execution_status:str='EXECUTED',**extra):
        return {'schema_version':'2.0','run_id':run_id,'case_id':self.case['id'],'case_sha256':digest(self.case),'principal':self.case['principal'],'origin':'evaluator_gateway','execution_status':execution_status,'fixture_sha256':self.before,'fixture_after_sha256':digest(self.graph.data),'initial_context':copy.deepcopy(self.initial_context),'events':copy.deepcopy(self.events),'wall_clock_ms':round((time.monotonic()-self.started)*1000,3),'input_tokens':None,'output_tokens':None,'token_measurement':'NOT_MEASURED','mode':'offline_fixture','measurement_note':'backend_requests=0 means no OpenCTI requests; fixture_operations are counted separately.',**extra}