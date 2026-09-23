"""JSON-lines subprocess driver. Process separation is NOT a security sandbox."""
from __future__ import annotations
import json, os, queue, subprocess, threading, time, uuid
from pathlib import Path
from .gateway import Gateway, TOOL_SCHEMAS
from .store import Graph, digest, ROOT, load_json
from .grading import sign_audit, grade
MAX_FRAME=262144

def run_case(case:dict,gold:dict,command:list[str],out:Path,audit_key:bytes,pass_env:list[str]|None=None) -> dict:
    out.mkdir(parents=True,exist_ok=True)
    gateway=Gateway(case,gold.get('faults')); run_id=str(uuid.uuid4()); answer=None
    execution='EXECUTED'; reason=None; start=time.monotonic(); process=None
    safe_env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','SYSTEMROOT','LANG','LC_ALL','TMPDIR')}
    for k in pass_env or []:
        if k in os.environ: safe_env[k]=os.environ[k]
    safe_env['PYTHONUNBUFFERED']='1'
    # The child only receives the public case and ACL-filtered context. For hostile
    # candidates an OS sandbox must additionally hide evaluator_private and files.
    request={'answer_schema':load_json(ROOT/'schemas/answer.schema.json'),'query_schema':load_json(ROOT/'schemas/query.schema.json'),'type':'task','case':case,'context':gateway.initial_context,'tools':{k:{'required':{a:t.__name__ for a,t in TOOL_SCHEMAS[k][0].items()},'optional':{a:t.__name__ for a,t in TOOL_SCHEMAS[k][1].items()}} for k in case['allowed_tools'] if k in TOOL_SCHEMAS},'instructions':'Respond with JSON-lines tool_call messages or one final message; use schema answer-v2. Do not output thoughts or logs on stdout.'}
    try:
        with (out/'candidate.stderr.txt').open('w',encoding='utf-8') as stderr:
            process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,text=True,encoding='utf-8',env=safe_env,bufsize=1)
            messages=queue.Queue(maxsize=4)
            def reader():
                try:
                    while True:
                        line=process.stdout.readline(MAX_FRAME+1)
                        if not line: messages.put(None); break
                        if len(line)>MAX_FRAME: messages.put(RuntimeError('FRAME_TOO_LARGE')); break
                        messages.put(line)
                except Exception as exc: messages.put(exc)
            thread=threading.Thread(target=reader,daemon=True); thread.start()
            process.stdin.write(json.dumps(request,ensure_ascii=False)+'\n'); process.stdin.flush()
            frames=0
            while True:
                remaining=case['budget']['wall_seconds']-(time.monotonic()-start)
                if remaining<=0: raise TimeoutError('RUN_DEADLINE')
                try: line=messages.get(timeout=remaining)
                except queue.Empty as exc: raise TimeoutError('RUN_DEADLINE') from exc
                if line is None: raise RuntimeError('CANDIDATE_EXITED_WITHOUT_FINAL')
                if isinstance(line,Exception): raise line
                frames+=1
                if frames>case['budget']['max_tool_calls']+4: raise RuntimeError('PROTOCOL_FRAME_BUDGET')
                msg=json.loads(line)
                if type(msg) is not dict: raise RuntimeError('INVALID_PROTOCOL_OBJECT')
                if msg.get('type')=='tool_call':
                    if set(msg)-{'type','id','tool','args'} or type(msg.get('id')) is not str or type(msg.get('tool')) is not str or type(msg.get('args')) is not dict: raise RuntimeError('INVALID_TOOL_ENVELOPE')
                    result=gateway.call(msg['tool'],msg['args'])
                    process.stdin.write(json.dumps({'type':'tool_result','id':msg['id'],'result':result},ensure_ascii=False)+'\n'); process.stdin.flush()
                elif msg.get('type')=='final':
                    answer=msg.get('answer')
                    if type(answer) is not dict: raise RuntimeError('FINAL_MUST_BE_OBJECT')
                    break
                else: raise RuntimeError('UNKNOWN_PROTOCOL_MESSAGE')
    except Exception as exc:
        execution='RUN_ERROR'; reason=f'{type(exc).__name__}: {exc}'
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=2)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=2)
            if process.stdin: process.stdin.close()
            if process.stdout: process.stdout.close()
    # The submitted query is run unchanged by the evaluator. This is fixture AST,
    # not a claim to implement OpenCTI's version-specific GraphQL filter format.
    if execution=='EXECUTED' and gold['kind']=='query' and type(answer) is dict and type(answer.get('query')) is dict:
        cursor=0
        while True:
            r=gateway.call('query_graph',{'query':answer['query'],'cursor':cursor},actor='evaluator')
            if not r.get('ok') or not r.get('has_next_page'): break
            cursor=r['next_cursor']
    audit=gateway.audit(run_id,execution,reason=reason,command_sha256=digest(command),answer_sha256=digest(answer) if answer is not None else None)
    signed=sign_audit(audit,audit_key)
    (out/'audit.json').write_text(json.dumps(signed,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if answer is not None: (out/'answer.json').write_text(json.dumps(answer,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    result=grade(case,gold,answer,audit,trusted_audit=True)
    (out/'score.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result