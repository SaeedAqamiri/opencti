"""Machine-readable contracts; Python grader performs additional semantic checks."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from ctibench.gateway import TOOL_SCHEMAS

def save(name,x):
    (ROOT/'schemas'/name).write_text(json.dumps(x,indent=2)+'\n')
S={'type':'string'}; ARR={'type':'array','items':S,'uniqueItems':True}
relation={'type':'object','additionalProperties':False,'required':['kind','subject','predicate','object','evidence_ids'],'properties':{'kind':{'const':'relation'},'subject':S,'predicate':S,'object':S,'evidence_ids':{**ARR,'minItems':1}}}
path={'type':'object','additionalProperties':False,'required':['kind','nodes','edge_ids'],'properties':{'kind':{'const':'path'},'nodes':{'type':'array','items':S,'minItems':2},'edge_ids':{'type':'array','items':S,'minItems':1}}}
variants=[]
def variant(op,req,extra=None):
    props={'op':{'const':op},**req,**(extra or {})}; variants.append({'type':'object','additionalProperties':False,'required':['op']+list(req),'properties':props})
variant('search',{'name':S},{'entity_type':S})
variant('neighbors',{'key':S,'predicate':S,'direction':{'enum':['in','out']},'target_type':S,'active_only':{'type':'boolean'}})
variant('intersection',{'left':S,'right':S,'target_type':S})
variant('shared_threshold',{'key':S,'minimum':{'type':'integer','minimum':1,'maximum':1000}})
variant('mitigations_for',{'key':S})
variant('campaigns_between',{'start':{**S,'format':'date-time'},'end':{**S,'format':'date-time'}})
variant('valid_indicators',{'as_of':{**S,'format':'date-time'}})
query={'$schema':'https://json-schema.org/draft/2020-12/schema','title':'Fixture query AST; NOT an OpenCTI GraphQL filter','oneOf':variants}
save('query.schema.json',query)
answer={'$schema':'https://json-schema.org/draft/2020-12/schema','title':'Answer v2','type':'object','additionalProperties':False,'required':['case_id','answer_state','complete','answer','entity_keys','values','claims','citations'],'properties':{'case_id':S,'answer_state':{'enum':['ANSWERED','EMPTY','INCOMPLETE','INSUFFICIENT_EVIDENCE','REFUSED','NEEDS_CLARIFICATION']},'complete':{'type':'boolean'},'answer':S,'entity_keys':ARR,'values':{'type':'object'},'claims':{'type':'array','items':{'oneOf':[relation,path]}},'citations':ARR,'query':query}}
save('answer.schema.json',answer)
review={'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','required':['case_id','answer_sha256','fixture_sha256','reviewer_id','rubric_version','factuality','coverage','uncertainty','citation_alignment','style','verdict'],'properties':{**{k:S for k in ['case_id','answer_sha256','fixture_sha256','reviewer_id']},'rubric_version':{'const':'2.0'},**{k:{'type':'integer','minimum':0,'maximum':4} for k in ['factuality','coverage','uncertainty','citation_alignment','style']},'verdict':{'enum':['PASS','FAIL']},'notes':S,'evidence_notes':{'type':'array','items':S}}}
save('review.schema.json',review)
mp={str:'string',int:'integer',bool:'boolean',dict:'object',list:'array'}
save('tools.schema.json',{'tools':{name:{'type':'object','additionalProperties':False,'required':list(req),'properties':{k:{'type':mp[t]} for k,t in {**req,**opt}.items()}} for name,(req,opt) in TOOL_SCHEMAS.items()}})
save('audit.schema.json',{'$schema':'https://json-schema.org/draft/2020-12/schema','title':'Evaluator audit (HMAC validated by CLI)','type':'object','required':['schema_version','run_id','case_id','principal','origin','execution_status','fixture_sha256','fixture_after_sha256','initial_context','events','wall_clock_ms','signature'],'properties':{'schema_version':{'const':'2.0'},'origin':{'const':'evaluator_gateway'},'execution_status':{'enum':['EXECUTED','NOT_RUN','SKIPPED','ENV_INVALID','RUN_ERROR']},'events':{'type':'array','items':{'type':'object','required':['event_id','tool','args','result','write_attempted','write_executed','duration_ms','output_bytes','backend_requests']}}}})
save('case.schema.json',{'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','required':['id','suite','phase','action','prompt','language','split','principal','as_of','allowed_tools','budget','output_requirements'],'properties':{'id':{'type':'string','pattern':'^[ABC][0-9]{2}$'},'suite':{'enum':['A','B','C']},'phase':{'type':'integer','minimum':1,'maximum':5},'language':{'enum':['en','fa']},'split':{'const':'public_regression'},'allowed_tools':{'type':'array','items':S},'budget':{'type':'object'},'output_requirements':{'type':'object'}}})
save('golden.schema.json',{'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','required':['case_id','kind','expected_state','expected_complete','expected_keys','expected_values','requires_human_review','checks','required_claims','required_evidence','reference_query','faults','security'],'properties':{'case_id':S,'kind':{'enum':['text','set','narrative','narrative_set','values','query','partial_set','safety']},'expected_complete':{'type':'boolean'},'expected_keys':ARR,'expected_values':{'type':'object'},'requires_human_review':{'type':'boolean'},'choice_fields':{'type':'object'},'semantic_reference':{'type':'object'}}})
print('Wrote 7 schemas')