"""OpenCTI AI benchmark harness.

Usage:
  python3 run_benchmark.py --phase 1     # text actions (works today)
  python3 run_benchmark.py --phase 2     # container report
  python3 run_benchmark.py --phase 3     # AI insights
  python3 run_benchmark.py --phase 4     # NLQ
  python3 run_benchmark.py --all
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import (check, case_score, gql, has_html, jaccard, length_ratio,  # noqa: E402
                 similarity, word_overlap)

CASES = Path(__file__).parent / 'cases'
OUT = Path(__file__).parent / 'out'
OUT.mkdir(exist_ok=True)

PHASE_NAMES = {1: 'text_actions', 2: 'container_report', 3: 'insights', 4: 'nlq'}
EE_MARKERS = ('Enterprise edition', 'ENTERPRISE')


def is_ee_error(err: str) -> bool:
    return any(m.lower() in err.lower() for m in EE_MARKERS)


def run_mutation(mutation: str, variables: dict):
    last = None
    for attempt in range(3):
        try:
            return gql(mutation, variables)
        except Exception as e:  # noqa: BLE001
            last = e
            if 'Connection error' in str(e) or 'terminated' in str(e):
                time.sleep(5 * (attempt + 1))
                continue
            raise
    raise last  # noqa: TRY002


# ─────────────────────────────── phase 1 ─────────────────────────────────

def run_phase1():
    cases = json.load(open(CASES / 'text_actions.json'))
    results = []
    for c in cases:
        action, src = c['action'], c['input']
        checks, out = [], ''
        try:
            if action == 'fixSpelling':
                out = run_mutation(
                    f'mutation B($content: String!) {{ aiFixSpelling(id: "bench", content: $content, format: {fmt_enum(c["format"])}) }}',
                    {'content': src})['aiFixSpelling']
                checks.append(check('no-typos-restored', similarity(out, c['reference']) > 0.75,
                                    f'similarity={similarity(out, c["reference"]):.2f}'))
                checks.append(check('length-preserved', 0.6 < length_ratio(out, src) < 1.6,
                                    f'ratio={length_ratio(out, src):.2f}'))
            elif action == 'makeShorter':
                out = run_mutation(
                    f'mutation B($content: String!) {{ aiMakeShorter(id: "bench", content: $content, format: {fmt_enum(c["format"])}) }}',
                    {'content': src})['aiMakeShorter']
                checks.append(check('shorter', length_ratio(out, src) < 0.8,
                                    f'ratio={length_ratio(out, src):.2f}'))
                checks.append(check('keywords-kept', word_overlap(out, src) >= 0.5,
                                    f'overlap={word_overlap(out, src):.2f}'))
            elif action == 'makeLonger':
                out = run_mutation(
                    f'mutation B($content: String!) {{ aiMakeLonger(id: "bench", content: $content, format: {fmt_enum(c["format"])}) }}',
                    {'content': src})['aiMakeLonger']
                checks.append(check('longer', length_ratio(out, src) > 1.3,
                                    f'ratio={length_ratio(out, src):.2f}'))
                checks.append(check('keywords-kept', word_overlap(out, src) >= 0.6,
                                    f'overlap={word_overlap(out, src):.2f}'))
            elif action == 'changeTone':
                out = run_mutation(
                    f'mutation B($content: String!) {{ aiChangeTone(id: "bench", content: $content, format: {fmt_enum(c["format"])}, tone: {c["tone"]}) }}',
                    {'content': src})['aiChangeTone']
                checks.append(check('length-similar', 0.5 < length_ratio(out, src) < 1.7,
                                    f'ratio={length_ratio(out, src):.2f}'))
                checks.append(check('content-kept', word_overlap(out, src, 12) >= 0.4,
                                    f'overlap={word_overlap(out, src, 12):.2f}'))
            elif action == 'summarize':
                out = run_mutation(
                    f'mutation B($content: String!) {{ aiSummarize(id: "bench", content: $content, format: {fmt_enum(c["format"])}) }}',
                    {'content': src})['aiSummarize']
                checks.append(check('actually-shorter', length_ratio(out, src) < 0.85,
                                    f'ratio={length_ratio(out, src):.2f}'))
                checks.append(check('keywords-kept', word_overlap(out, src) >= 0.5,
                                    f'overlap={word_overlap(out, src):.2f}'))
            elif action == 'explain':
                out = run_mutation(
                    f'mutation B($content: String!) {{ aiExplain(id: "bench", content: $content) }}',
                    {'content': src})['aiExplain']
                checks.append(check('plain-text', not has_html(out), ''))
                checks.append(check('substantive', len(out) > 200, f'len={len(out)}'))
            checks.append(check('non-error', not out.startswith('An error occurred'), out[:120]))
        except Exception as e:  # noqa: BLE001
            err = str(e)
            status = 'SKIP-EE' if is_ee_error(err) else 'ERROR'
            results.append({'case': c['id'], 'phase': 1, 'status': status, 'score': 0.0,
                            'checks': [], 'error': err[:300], 'output': ''})
            continue
        results.append({'case': c['id'], 'phase': 1, 'status': 'OK',
                        'score': case_score(checks), 'checks': checks,
                        'output': out[:400]})
        time.sleep(1)
    return results


def fmt_enum(fmt: str) -> str:
    return {'text': 'text', 'html': 'html', 'markdown': 'markdown', 'json': 'json'}.get(fmt, 'text')


# ─────────────────────────────── phase 2 ─────────────────────────────────

def run_phase2():
    cfg = json.load(open(CASES / 'container_report.json'))
    obj_ids = [o['id'] for o in cfg['objects']]
    results = []
    checks, report = [], ''
    try:
        data = gql('''mutation ReportAdd($name: String!, $objects: [String]) {
          reportAdd(input: { name: $name, published: "2026-09-15T00:00:00.000Z", objects: $objects }) { id }
        }''', {'name': cfg['container_name'], 'objects': obj_ids})
        container_id = data['reportAdd']['id']
        time.sleep(2)
        report = run_mutation(
            'mutation B($cid: String!) { aiContainerGenerateReport(id: "bench", containerId: $cid, '
            'paragraphs: 8, tone: tactical, format: html, language: "en-us") }',
            {'cid': container_id})['aiContainerGenerateReport']
        names = cfg['entity_names']
        found = [n for n in names if n and n.lower() in report.lower()]
        recall = len(found) / max(len([n for n in names if n]), 1)
        checks.append(check('non-error', not report.startswith('An error occurred'), report[:120]))
        paras = len(re.findall(r'<p[ >]', report, re.I))
        checks.append(check('paragraph-count', 4 <= paras <= 20, f'p={paras}'))
        checks.append(check('entity-recall>=0.5', recall >= 0.5, f'{len(found)}/{len(names)}={recall:.2f}'))
        checks.append(check('has-structure', bool(re.search(r'<(h[12]|table)', report, re.I)), ''))
    except Exception as e:  # noqa: BLE001
        err = str(e)
        status = 'SKIP-EE' if is_ee_error(err) else 'ERROR'
        return [{'case': 'container-report', 'phase': 2, 'status': status, 'score': 0.0,
                 'checks': [], 'error': err[:300], 'output': ''}]
    return [{'case': 'container-report', 'phase': 2, 'status': 'OK',
             'score': case_score(checks), 'checks': checks, 'output': report[:500]}]


# ─────────────────────────────── phase 3 ─────────────────────────────────

def run_phase3():
    cfg = json.load(open(CASES / 'insights.json'))
    target = cfg['activity_target']
    results = []

    # Activity
    try:
        d = gql('''query A($id: ID!, $lang: String) {
          stixCoreObjectAskAiActivity(id: $id, language: $lang) { result trend }
        }''', {'id': target['id'], 'lang': 'English'}, timeout=900)
        act = d['stixCoreObjectAskAiActivity']
        checks = [
            check('non-empty', len(act['result'] or '') > 200, f'len={len(act["result"] or "")}'),
            check('valid-trend', act['trend'] in ('increasing', 'stable', 'decreasing', 'unknown'),
                  f'trend={act["trend"]}'),
            check('mentions-entity', target['name'].lower() in (act['result'] or '').lower(), target['name']),
        ]
        results.append({'case': 'insights-activity', 'phase': 3, 'status': 'OK',
                        'score': case_score(checks), 'checks': checks,
                        'output': (act['result'] or '')[:300]})
    except Exception as e:  # noqa: BLE001
        err = str(e)
        results.append({'case': 'insights-activity', 'phase': 3,
                        'status': 'SKIP-EE' if is_ee_error(err) else 'ERROR', 'score': 0.0,
                        'checks': [], 'error': err[:300], 'output': ''})

    # History
    try:
        d = gql('''query H($id: ID!, $lang: String) {
          stixCoreObjectAskAiHistory(id: $id, language: $lang) { result }
        }''', {'id': target['id'], 'lang': 'English'}, timeout=900)
        res = d['stixCoreObjectAskAiHistory']['result'] or ''
        checks = [check('non-empty', len(res) > 100, f'len={len(res)}'),
                  check('non-error', not res.startswith('An error occurred'), res[:120])]
        results.append({'case': 'insights-history', 'phase': 3, 'status': 'OK',
                        'score': case_score(checks), 'checks': checks, 'output': res[:300]})
    except Exception as e:  # noqa: BLE001
        err = str(e)
        results.append({'case': 'insights-history', 'phase': 3,
                        'status': 'SKIP-EE' if is_ee_error(err) else 'ERROR', 'score': 0.0,
                        'checks': [], 'error': err[:300], 'output': ''})
    return results


# ─────────────────────────────── phase 4 ─────────────────────────────────

def run_phase4():
    cases = json.load(open(CASES / 'nlq.json'))
    results = []
    for c in cases:
        checks = []
        try:
            d = gql('mutation N($search: String!) { aiNLQ(search: $search) { filters notResolvedValues } }',
                    {'search': c['question']})
            filters_raw = d['aiNLQ']['filters']
            filters = json.loads(filters_raw)
            checks.append(check('filters-produced', bool(filters.get('filters')), str(filters)[:120]))
            golden_names = set(c.get('golden_names') or [])
            if golden_names:
                typed = {
                    'Intrusion-Set': ('intrusionSets', 'IntrusionSet'),
                    'Tool': ('tools', 'Tool'),
                    'Malware': ('malwares', 'Malware'),
                    'Attack-Pattern': ('attackPatterns', 'AttackPattern'),
                    'Course-Of-Action': ('coursesOfAction', 'CourseOfAction'),
                }.get(c.get('expect_entity_type'))
                if typed:
                    field, frag = typed
                    data = gql(f'''query S($filters: FilterGroup, $first: Int) {{
                      {field}(first: $first, filters: $filters) {{ edges {{ node {{ ... on {frag} {{ name }} }} }} }}
                    }}''', {'filters': filters, 'first': 1000}, timeout=240)
                    got = {e['node']['name'] for e in data[field]['edges'] if e['node'].get('name')}
                    j = jaccard(golden_names, got)
                    prec = len(golden_names & got) / max(len(got), 1)
                    rec = len(golden_names & got) / max(len(golden_names), 1)
                    checks.append(check('jaccard>=0.3', j >= 0.3, f'j={j:.2f} p={prec:.2f} r={rec:.2f}'))
        except Exception as e:  # noqa: BLE001
            err = str(e)
            results.append({'case': c['id'], 'phase': 4,
                            'status': 'SKIP-EE' if is_ee_error(err) else 'ERROR', 'score': 0.0,
                            'checks': [], 'error': err[:300], 'output': ''})
            continue
        results.append({'case': c['id'], 'phase': 4, 'status': 'OK',
                        'score': case_score(checks), 'checks': checks, 'output': filters_raw[:300]})
        time.sleep(1)
    return results


# ─────────────────────────────── main ────────────────────────────────────

RUNNERS = {1: run_phase1, 2: run_phase2, 3: run_phase3, 4: run_phase4}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', type=int, choices=[1, 2, 3, 4])
    ap.add_argument('--all', action='store_true')
    args = ap.parse_args()
    phases = [1, 2, 3, 4] if args.all else [args.phase]
    all_results = []
    for p in phases:
        print(f'── phase {p} ({PHASE_NAMES[p]}) …', flush=True)
        all_results.extend(RUNNERS[p]())

    scores = {}
    for p in phases:
        rs = [r for r in all_results if r['phase'] == p]
        ok = [r['score'] for r in rs if r['status'] == 'OK']
        scores[p] = {
            'category': PHASE_NAMES[p],
            'cases': len(rs),
            'passed_avg': round(sum(ok) / len(ok), 2) if ok else 0.0,
            'status': ('OK' if all(r['status'] == 'OK' for r in rs)
                       else 'PARTIAL' if any(r['status'] == 'OK' for r in rs)
                       else rs[0]['status']),
        }

    lines = ['# AI Benchmark Report', '',
             f'_generated: {time.strftime("%Y-%m-%d %H:%M:%S")}_', '']
    for p, s in scores.items():
        lines.append(f"## Phase {p} — {s['category']}: **{s['passed_avg']}** ({s['status']})")
        for r in (x for x in all_results if x['phase'] == p):
            lines.append(f"- `{r['case']}` {r['status']} score={r['score']:.2f}")
            for c in r['checks']:
                lines.append(f"  - {'✅' if c['pass'] else '❌'} {c['check']} {c['detail']}")
            if r.get('error'):
                lines.append(f"  - error: {r['error'][:200]}")
        lines.append('')
    (OUT / 'report.md').write_text('\n'.join(lines))
    json.dump({'scores': scores, 'results': all_results}, open(OUT / 'scores.json', 'w'), indent=2)
    print(json.dumps(scores, indent=2))
    print('report →', OUT / 'report.md')


if __name__ == '__main__':
    main()
