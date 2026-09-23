"""CLI: validate, list, run, grade. No model or OpenCTI access is implicit."""
from __future__ import annotations
import argparse, hashlib, json, os, platform, secrets, shlex, sys
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
from .store import ROOT,Graph,cases,goldens,load_json,digest
from .grading import grade,summarize,verify_audit
from .runner import run_case

def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def validate(quiet=False):
    cs=cases(); gs=goldens(); g=Graph(); errors=[]
    if set(cs)!=set(gs): errors.append('case/golden IDs mismatch')
    allkeys=[n['key'] for n in g.data['nodes']]+[e['key'] for e in g.data['edges']]+[d['key'] for d in g.data['documents']]
    if len(allkeys)!=len(set(allkeys)): errors.append('duplicate fixture identities')
    nodes={n['key'] for n in g.data['nodes']}; docs={d['key'] for d in g.data['documents']}
    for e in g.data['edges']:
        if e['source'] not in nodes or e['target'] not in nodes or e['source_document'] not in docs: errors.append('dangling edge '+e['key'])
    for cid,c in cs.items():
        gold=gs[cid]; view=Graph(principal=c['principal'])
        if not set(gold['expected_keys'])<=set(view.nodes): errors.append('gold outside permitted view '+cid)
        if not set(gold.get('required_evidence',[]))<=set(view.records): errors.append('unknown required evidence '+cid)
        if gold.get('reference_query') is not None:
            actual=view.query(gold['reference_query'])[0]
            if actual!=gold['expected_keys']: errors.append('independent query/gold mismatch '+cid)
    manifest=ROOT/'manifest.sha256.json'
    if manifest.exists():
        for p,h in load_json(manifest).items():
            path=ROOT/p
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=h: errors.append('checksum mismatch '+p)
    else: errors.append('manifest.sha256.json missing')
    report={'ok':not errors,'errors':errors,'cases':len(cs),'suites':dict(Counter(c['suite'] for c in cs.values())),'nodes':len(nodes),'edges':len(g.data['edges']),'documents':len(docs),'synthetic':True,'real_snapshots_verified':False}
    if not quiet: print(json.dumps(report,indent=2))
    return 0 if not errors else 2

def main():
    p=argparse.ArgumentParser(description='OpenCTI AI Bench v2 - synthetic reference implementation')
    sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('validate')
    ls=sub.add_parser('list'); ls.add_argument('--suite',choices=['A','B','C'])
    r=sub.add_parser('run'); r.add_argument('--case',action='append'); r.add_argument('--suite',choices=['A','B','C']); r.add_argument('--agent-command',required=True); r.add_argument('--out',required=True); r.add_argument('--repeat',type=int,default=1); r.add_argument('--pass-env',action='append',default=[]); r.add_argument('--audit-key',help='Evaluator-owned secret file, never pass to candidate'); r.add_argument('--metadata',help='Optional experiment metadata JSON')
    gr=sub.add_parser('grade'); gr.add_argument('--run-dir',required=True); gr.add_argument('--audit-key',required=True); gr.add_argument('--reviews-dir')
    args=p.parse_args()
    if args.cmd=='validate': return validate()
    cs=cases(); gs=goldens()
    if args.cmd=='list':
        for c in cs.values():
            if not args.suite or c['suite']==args.suite: print(c['id'],c['suite'],c['action'],c['prompt'])
        return 0
    if args.cmd=='run':
        if validate(quiet=True): p.error('Preflight failed; run python -m ctibench validate')
        if not 1<=args.repeat<=100: p.error('--repeat must be 1..100')
        selected=[c for c in cs.values() if (not args.case or c['id'] in args.case) and (not args.suite or c['suite']==args.suite)]
        if not selected or args.case and set(args.case)-set(cs): p.error('No matching cases or unknown case')
        out=Path(args.out).resolve()
        if (out/'run.json').exists(): p.error('Run directory already contains run.json; choose a new directory')
        out.mkdir(parents=True,exist_ok=True)
        keypath=Path(args.audit_key).resolve() if args.audit_key else out/'.audit-key'
        if not keypath.exists():
            keypath.parent.mkdir(parents=True,exist_ok=True); keypath.write_bytes(secrets.token_bytes(32)); keypath.chmod(0o600)
        key=keypath.read_bytes()
        if len(key)<32: p.error('Audit key must contain at least 32 bytes')
        meta=load_json(args.metadata) if args.metadata else {}
        run={'benchmark_version':'2.0.0','case_ids':[c['id'] for c in selected],'repetitions':args.repeat,'started_at':datetime.now(timezone.utc).isoformat(),'python':sys.version,'platform':platform.platform(),'fixture_sha256':digest(Graph().data),'metadata':meta,'audit_key_location':'external' if args.audit_key else 'local .audit-key (development only)','security_scope':'Local process boundary, NOT an OS sandbox','mode':'offline_fixture'}
        dump(out/'run.json',run)
        results=[]; command=shlex.split(args.agent_command)
        if not command: p.error('Empty agent command')
        for rep in range(1,args.repeat+1):
            for c in selected:
                result=run_case(c,gs[c['id']],command,out/f'repeat-{rep:02d}'/c['id'],key,args.pass_env)
                result['repeat']=rep; results.append(result); print(c['id'],rep,result['status'])
        dump(out/'results.json',results); dump(out/'summary.json',summarize(results))
        print(json.dumps(summarize(results),indent=2)); print('Do not publish .audit-key. No live OpenCTI run is implied.')
        return 0
    if args.cmd=='grade':
        out=Path(args.run_dir); run=load_json(out/'run.json'); key=Path(args.audit_key).read_bytes(); results=[]
        for rep in range(1,run['repetitions']+1):
            for cid in run['case_ids']:
                folder=out/f'repeat-{rep:02d}'/cid
                audit=load_json(folder/'audit.json') if (folder/'audit.json').exists() else None
                answer=load_json(folder/'answer.json') if (folder/'answer.json').exists() else None
                review_path=Path(args.reviews_dir)/f'repeat-{rep:02d}'/(cid+'.json') if args.reviews_dir else None
                review=load_json(review_path) if review_path and review_path.exists() else None
                result=grade(cs[cid],gs[cid],answer,audit,review,trusted_audit=bool(audit and verify_audit(audit,key)))
                result['repeat']=rep; results.append(result)
        dump(out/'results.json',results); dump(out/'summary.json',summarize(results)); print(json.dumps(summarize(results),indent=2)); return 0
    return 2
if __name__=='__main__': raise SystemExit(main())