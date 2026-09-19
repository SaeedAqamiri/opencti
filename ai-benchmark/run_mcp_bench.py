"""MCP transport bench — M-suite.

Runs the regression tasks t1-t7 through the agent's MCP transport (what the
XTM One MCP card would expose) and grades them with the SAME v1 grader as the
direct transport. Gate per task: capability score parity (±0.05) with the
direct-transport reference artifacts.

Usage:
  python3 run_mcp_bench.py                       # transport mcp (stdio)
  python3 run_mcp_bench.py --transport mcp-http  # the HTTP transport to be
                                                 # added for the profile MCP card
  python3 run_mcp_bench.py --skip-run            # re-grade existing artifacts

Artifacts land in out/mcp_artifacts_<transport>/. Reference (direct) scores
come from out/agent_bench_scores.json when present, else from
<path-to-agent>/artifacts graded inline.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from run_agent_bench import grade  # noqa: E402

AGENT_DIR = Path(__file__).parent.parent.parent / 'opencti-agent'
TASKS = HERE / 'agent_bench' / 'tasks.json'
REGRESSION = ['t1-apt28-tools', 't2-shared-malware', 't3-kimsuky-neighbors',
              't4-investigate-ioc', 't5-actor-profile', 't6-coa-two-hop',
              't7-write-probe']
OUT = HERE / 'out'


def run_task(task_id: str, transport: str, out_dir: Path) -> tuple[bool, str]:
    cmd = [str(AGENT_DIR / '.venv' / 'bin' / 'python'), 'cli.py',
           '--task', task_id, '--transport', transport,
           '--out', str(out_dir / f'{task_id}.json')]
    try:
        proc = subprocess.run(cmd, cwd=AGENT_DIR, capture_output=True, text=True,
                              timeout=300)
    except FileNotFoundError:
        return False, f'agent venv/CLI not found at {AGENT_DIR}'
    except subprocess.TimeoutExpired:
        return False, f'{task_id}: timeout after 300s'
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or '').strip().splitlines()
        tail = err[-1] if err else f'exit={proc.returncode}'
        if 'invalid choice' in (proc.stderr or '') and transport in tail:
            return False, f'transport {transport!r} not supported by agent CLI yet'
        return False, f'{task_id}: {tail[:200]}'
    return True, ''


def build_fresh_reference(tasks: dict, out_dir: Path) -> dict:
    """Run the same tasks over the direct transport and grade them — the
    honest same-session reference for parity (committed scores go stale)."""
    ref_dir = OUT / 'direct_reference'
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref = {}
    for tid in tasks:
        art_path = ref_dir / f'{tid}.json'
        ok, msg = run_task(tid, 'direct', ref_dir)
        if not ok:
            notes_append(str(msg))
            continue
        art = json.load(open(art_path))
        ref[tid] = grade(tasks[tid], art)['score']
    return ref


_NOTES: list[str] = []


def notes_append(msg: str):
    _NOTES.append(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--transport', default='mcp', choices=['mcp', 'mcp-http'])
    ap.add_argument('--skip-run', action='store_true',
                    help='grade artifacts already in the output dir (reference from scores files)')
    ap.add_argument('--reference-scores', default=str(OUT / 'agent_bench_scores.json'))
    args = ap.parse_args()

    out_dir = OUT / f'mcp_artifacts_{args.transport}'
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = {t['id']: t for t in json.load(open(TASKS))}

    results, notes = [], []
    for tid in REGRESSION:
        if not args.skip_run:
            ok, msg = run_task(tid, args.transport, out_dir)
            if not ok:
                notes.append(msg)
                results.append({'task': tid, 'status': 'SKIP-PENDING', 'score': None,
                                'error': msg})
                continue
        art_path = out_dir / f'{tid}.json'
        if not art_path.exists():
            results.append({'task': tid, 'status': 'SKIP-PENDING', 'score': None,
                            'error': 'no artifact (run not executed)'})
            continue
        art = json.load(open(art_path))
        graded = grade(tasks[tid], art)
        results.append({'task': tid, 'status': 'OK', **graded})

    # reference scores for parity: fresh direct run when we executed the MCP
    # transport just now; otherwise fall back to the committed scores files.
    ref: dict = {}
    if not args.skip_run:
        ref = build_fresh_reference(tasks, out_dir)
        notes.extend(_NOTES)
    if not ref:
        for cand in (Path(args.reference_scores), OUT / 'agent_bench_scores_v2.json'):
            if not Path(cand).exists():
                continue
            try:
                data = json.load(open(cand))
                items = data.get('results') if isinstance(data, dict) else data
                if not items:
                    continue
                for r in items:
                    tid = r.get('task')
                    score = r.get('score')
                    cap = r.get('capability_score')
                    if tid and (score is not None or cap is not None):
                        ref.setdefault(tid, cap if cap is not None else score)
            except (json.JSONDecodeError, AttributeError):
                continue

    lines = [f'# MCP Transport Bench ({args.transport})',
             f'_{time.strftime("%Y-%m-%d %H:%M")}_', '']
    ok_scores = []
    for r in results:
        if r['status'] != 'OK':
            lines.append(f"- `{r['task']}` **SKIP-PENDING** — {r.get('error')}")
            continue
        score = r['score']
        ok_scores.append(score)
        parity = ref.get(r['task'])
        if parity is None:
            lines.append(f"- `{r['task']}` score={score:.2f} (no reference — parity n/a)")
            r['parity'] = None
        else:
            delta = abs(score - parity)
            r['parity'] = {'reference': parity, 'delta': round(delta, 3),
                           'pass': delta <= 0.05}
            lines.append(f"- `{r['task']}` score={score:.2f} vs direct {parity:.2f} "
                         f"→ parity {'✅' if delta <= 0.05 else '❌'} (Δ={delta:.2f})")
    for n in notes:
        lines.append(f"- note: {n}")
    summary = {
        'transport': args.transport,
        'tasks': len(results),
        'executed': len(ok_scores),
        'avg_score': round(sum(ok_scores) / len(ok_scores), 2) if ok_scores else None,
        'parity_pass': all(r.get('parity', {}).get('pass', True) for r in results
                           if r['status'] == 'OK' and r.get('parity')),
    }
    lines.insert(2, f"**avg = {summary['avg_score']}** ({summary['executed']}/{summary['tasks']} executed, "
                    f"parity {'PASS' if summary['parity_pass'] else 'FAIL'})")
    OUT.mkdir(exist_ok=True)
    (OUT / 'mcp_report.md').write_text('\n'.join(lines) + '\n')
    json.dump({'summary': summary, 'results': results},
              open(OUT / 'mcp_scores.json', 'w'), indent=2)
    print(json.dumps(summary, indent=2))
    print('report →', OUT / 'mcp_report.md')


if __name__ == '__main__':
    main()
