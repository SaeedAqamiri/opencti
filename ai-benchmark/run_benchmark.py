"""OpenCTI AI benchmark harness.

Usage:
  python3 run_benchmark.py --phase 1     # text actions (works today)
  python3 run_benchmark.py --phase 2     # container report
  python3 run_benchmark.py --phase 3     # AI insights
  python3 run_benchmark.py --phase 4     # NLQ
  python3 run_benchmark.py --phase 5     # insights extra (forecast + containers digest)
  python3 run_benchmark.py --phase 6     # agent NLQ (via /ai-agent/ask, PENDING until implemented)
  python3 run_benchmark.py --phase 7     # local chat sessions (functional, PENDING until implemented)
  python3 run_benchmark.py --phase 8     # playbook transform/send (PENDING until implemented)
  python3 run_benchmark.py --phase 9     # file -> STIX extraction (CISA + gold-graph narrative)
  python3 run_benchmark.py --phase 10    # agent threat report + indicator conversion
  python3 run_benchmark.py --all

Grader v2 additions:
  --suite regression|heldout|all   (default regression — the frozen v1 contract;
                                   held-out cases must not tune prompts/tools)
  --nlq-threshold X                (default 0.3; use --strict for 0.8)
  --strict                         exact-match becomes gating for NLQ
Every NLQ case records raw model filter, final applied filter and the executed
result set (metrics reported separately: precision / recall / exact-match).

Phases 5 runs against existing platform queries today. Phases 6-10 define the
frozen contract for the opencti-agent integration surfaces; until those
endpoints exist they report SKIP-PENDING (excluded from pass rates, listed in
the report) — same philosophy as SKIP-EE.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import (PendingEndpoint, agent_delete, agent_get, agent_post, check, case_score, gql,  # noqa: E402
                 has_html, jaccard, length_ratio, platform_object_count, refang,  # noqa: E402
                 similarity, word_overlap)  # noqa: E402
import text_checks as tc  # noqa: E402

CASES = Path(__file__).parent / 'cases'
CASES_V2 = CASES / 'v2'
OUT = Path(__file__).parent / 'out'
OUT.mkdir(exist_ok=True)

PHASE_NAMES = {1: 'text_actions', 2: 'container_report', 3: 'insights', 4: 'nlq',
               5: 'insights_extra', 6: 'agent_nlq', 7: 'chat_sessions', 8: 'playbook',
               9: 'file2stix', 10: 'agent_reports'}
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

def load_case_files(prefix: str) -> list:
    """Merge cases/<prefix>*.json (list or single dict), filtered by suite."""
    merged = []
    for f in sorted(CASES.glob(f'{prefix}*.json')):
        data = json.load(open(f))
        for c in (data if isinstance(data, list) else [data]):
            if c.get('suite', 'regression') in SUITES:
                merged.append(c)
    return merged


def run_phase1():
    cases = load_case_files('text_actions')
    results = []
    for c in cases:
        action, src = c['action'], c['input']
        checks, out = [], ''
        try:
            if action == 'fixSpelling':
                out = run_mutation(
                    f'mutation B($content: String!) {{ aiFixSpelling(id: "bench", content: $content, format: {fmt_enum(c["format"])}) }}',
                    {'content': src})['aiFixSpelling']
                # v2: were the *injected* corruptions actually repaired?
                rate, n_pairs = tc.typo_fix_rate(out, src, c['reference'])
                checks.append(check('injected-typos-fixed>=0.8', n_pairs == 0 or rate >= 0.8,
                                    f'rate={rate:.2f} of {n_pairs} injected'))
                damaged = tc.protected_token_damage(out, src)
                checks.append(check('protected-tokens-intact', not damaged,
                                    f'damaged={damaged[:3]}'))
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
                ok_cl, cl_det = tc.claims_ok(out, c.get('claims_required'), c.get('claims_forbidden'))
                checks.append(check('claims-preserved', ok_cl, str(cl_det)[:150]))
            elif action == 'makeLonger':
                out = run_mutation(
                    f'mutation B($content: String!) {{ aiMakeLonger(id: "bench", content: $content, format: {fmt_enum(c["format"])}) }}',
                    {'content': src})['aiMakeLonger']
                checks.append(check('longer', length_ratio(out, src) > 1.3,
                                    f'ratio={length_ratio(out, src):.2f}'))
                checks.append(check('keywords-kept', word_overlap(out, src) >= 0.6,
                                    f'overlap={word_overlap(out, src):.2f}'))
                checks.append(check('no-verbatim-padding', tc.ngram_repeats(out) == 0,
                                    f'repeated={tc.ngram_repeats(out)}'))
                nov = tc.novelty_ratio(out, src)
                checks.append(check('novel-content-added>=0.15', nov >= 0.15, f'novelty={nov:.2f}'))
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
                ok_cl, cl_det = tc.claims_ok(out, c.get('claims_required'), c.get('claims_forbidden'))
                checks.append(check('claims-preserved', ok_cl, str(cl_det)[:150]))
            elif action == 'explain':
                out = run_mutation(
                    f'mutation B($content: String!) {{ aiExplain(id: "bench", content: $content) }}',
                    {'content': src})['aiExplain']
                checks.append(check('plain-text', not has_html(out), ''))
                checks.append(check('substantive', len(out) > 200, f'len={len(out)}'))
            checks.append(check('non-error', not out.startswith('An error occurred'), out[:120]))
            checks.append(check('no-null-garbage', not re.search(r'(?:null|NaN){3,}', out),
                                'literal null/NaN repetition in model output' if re.search(r'(?:null|NaN){3,}', out) else ''))
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
    results = []
    for cfg in load_case_files('container_report'):
        obj_ids = [o['id'] for o in cfg['objects']]
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
            results.append({'case': cfg.get('container_name', 'container-report'), 'phase': 2, 'status': status, 'score': 0.0,
                            'checks': [], 'error': err[:300], 'output': ''})
            continue
        results.append({'case': cfg.get('container_name', 'container-report'), 'phase': 2, 'status': 'OK',
                        'score': case_score(checks), 'checks': checks, 'output': report[:500]})
    return results


# ─────────────────────────────── phase 3 ─────────────────────────────────

def run_insight_activity(target: dict, case_id: str, results: list):
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
        results.append({'case': case_id, 'phase': 3, 'status': 'OK',
                        'score': case_score(checks), 'checks': checks,
                        'output': (act['result'] or '')[:300]})
    except Exception as e:  # noqa: BLE001
        err = str(e)
        results.append({'case': case_id, 'phase': 3,
                        'status': 'SKIP-EE' if is_ee_error(err) else 'ERROR', 'score': 0.0,
                        'checks': [], 'error': err[:300], 'output': ''})


def run_insight_history(target: dict, case_id: str, results: list):
    try:
        d = gql('''query H($id: ID!, $lang: String) {
          stixCoreObjectAskAiHistory(id: $id, language: $lang) { result }
        }''', {'id': target['id'], 'lang': 'English'}, timeout=900)
        res = d['stixCoreObjectAskAiHistory']['result'] or ''
        checks = [check('non-empty', len(res) > 100, f'len={len(res)}'),
                  check('non-error', not res.startswith('An error occurred'), res[:120])]
        results.append({'case': case_id, 'phase': 3, 'status': 'OK',
                        'score': case_score(checks), 'checks': checks, 'output': res[:300]})
    except Exception as e:  # noqa: BLE001
        err = str(e)
        results.append({'case': case_id, 'phase': 3,
                        'status': 'SKIP-EE' if is_ee_error(err) else 'ERROR', 'score': 0.0,
                        'checks': [], 'error': err[:300], 'output': ''})


def run_phase3():
    results = []
    for cfg in load_case_files('insights'):
        base = (cfg.get('target_name') or cfg['activity_target'].get('name') or 'kimsuky').lower().replace(' ', '-')
        run_insight_activity(cfg['activity_target'], f'insights-activity-{base}', results)
        run_insight_history(cfg['history_target'], f'insights-history-{base}', results)
    return results


# ─────────────────────────────── phase 4 ─────────────────────────────────

def run_phase4():
    cases = load_case_files('nlq')
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
            metrics = {'jaccard': None, 'precision': None, 'recall': None, 'exact_match': None,
                       'result_count': None, 'raw_filter': filters_raw, 'final_filter': filters_raw}
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
                    exact = got == golden_names
                    metrics.update({'jaccard': round(j, 4), 'precision': round(prec, 4),
                                    'recall': round(rec, 4), 'exact_match': exact,
                                    'result_count': len(got)})
                    # audit trail: raw model filter vs the filter actually executed
                    if c.get('expected_final_filter_note'):
                        metrics['final_filter_note'] = c['expected_final_filter_note']
                    checks.append(check(f'jaccard>={CFG["nlq_threshold"]}', j >= CFG['nlq_threshold'],
                                        f'j={j:.2f} p={prec:.2f} r={rec:.2f}'))
                    if CFG['strict']:
                        checks.append(check('exact-match', exact,
                                            f'exact={exact} got={len(got)} gold={len(golden_names)}'))
        except Exception as e:  # noqa: BLE001
            err = str(e)
            results.append({'case': c['id'], 'phase': 4,
                            'status': 'SKIP-EE' if is_ee_error(err) else 'ERROR', 'score': 0.0,
                            'checks': [], 'error': err[:300], 'output': ''})
            continue
        results.append({'case': c['id'], 'phase': 4, 'status': 'OK',
                        'score': case_score(checks), 'checks': checks,
                        'metrics': metrics, 'output': filters_raw[:300]})
        time.sleep(1)
    return results


# ─────────────────────────────── phase 5 ─────────────────────────────────
# insights extra: forecast tab + containers digest (platform queries, ungated)

NULL_GARBAGE = re.compile(r'(?:null|NaN){3,}')


def load_v2(name: str) -> list:
    data = json.load(open(CASES_V2 / f'{name}.json'))
    if isinstance(data, dict):
        data = data.get('cases', [data])
    return [c for c in data if c.get('suite', 'regression') in SUITES]


def ensure_report(name: str, obj_ids: list[str]) -> str:
    """Find a report by exact name, create it once if absent (deterministic setup)."""
    d = gql('''query R($name: String) { reports(first: 5, search: $name) {
                edges { node { id name } } } }''', {'name': name})
    for e in d['reports']['edges']:
        if e['node']['name'] == name:
            return e['node']['id']
    created = gql('''mutation R($name: String!, $objects: [String]) {
      reportAdd(input: { name: $name, published: "2026-09-15T00:00:00.000Z", objects: $objects }) { id }
    }''', {'name': name, 'objects': obj_ids})
    time.sleep(2)
    return created['reportAdd']['id']


def run_insight_forecast(target: dict, case_id: str, results: list):
    try:
        d = gql('''query F($id: ID!, $lang: String) {
          stixCoreObjectAskAiForecast(id: $id, language: $lang) { result confidence }
        }''', {'id': target['id'], 'lang': 'English'}, timeout=900)
        fc = d['stixCoreObjectAskAiForecast']
        res = fc['result'] or ''
        checks = [
            check('non-empty', len(res) > 200, f'len={len(res)}'),
            check('valid-confidence', isinstance(fc['confidence'], int) and 0 <= fc['confidence'] <= 100,
                  f'confidence={fc["confidence"]}'),
            check('mentions-entity', target['name'].lower() in res.lower(), target['name']),
            check('no-null-garbage', not NULL_GARBAGE.search(res), ''),
        ]
        results.append({'case': case_id, 'phase': 5, 'status': 'OK',
                        'score': case_score(checks), 'checks': checks, 'output': res[:300]})
    except Exception as e:  # noqa: BLE001
        err = str(e)
        results.append({'case': case_id, 'phase': 5,
                        'status': 'SKIP-EE' if is_ee_error(err) else 'ERROR', 'score': 0.0,
                        'checks': [], 'error': err[:300], 'output': ''})


def run_insight_digest(cfg: dict, case_id: str, results: list):
    try:
        # golden entity names come from the container_report case set (same frozen objects)
        golden, obj_ids = [], []
        for cc in load_case_files('container_report'):
            if cc.get('container_name') == cfg.get('container_name'):
                golden = [n for n in cc.get('entity_names', []) if n]
                obj_ids = [o['id'] for o in cc.get('objects', [])]
        container_id = ensure_report(cfg['container_name'], obj_ids)
        d = gql('''query D($first: Int, $search: String, $lang: String) {
          containersAskAiSummary(first: $first, search: $search, language: $lang) { result topics }
        }''', {'first': 10, 'search': cfg['search'], 'lang': 'English'}, timeout=900)
        res = d['containersAskAiSummary']['result'] or ''
        found = [n for n in golden if n.lower() in res.lower()]
        recall = len(found) / max(len(golden), 1)
        checks = [
            check('non-error', not res.startswith('An error occurred'), res[:120]),
            check('non-empty', len(res) > 300, f'len={len(res)}'),
            check('entity-recall>=0.4', recall >= 0.4, f'{len(found)}/{len(golden)}={recall:.2f}'),
            check('no-null-garbage', not NULL_GARBAGE.search(res), ''),
        ]
        results.append({'case': case_id, 'phase': 5, 'status': 'OK',
                        'score': case_score(checks), 'checks': checks,
                        'metrics': {'entity_recall': round(recall, 3)}, 'output': res[:300]})
    except Exception as e:  # noqa: BLE001
        err = str(e)
        results.append({'case': case_id, 'phase': 5,
                        'status': 'SKIP-EE' if is_ee_error(err) else 'ERROR', 'score': 0.0,
                        'checks': [], 'error': err[:300], 'output': ''})


def run_phase5():
    results = []
    for cfg in load_v2('insights_extra'):
        if cfg['kind'] == 'forecast':
            run_insight_forecast(cfg['target'], cfg['id'], results)
        elif cfg['kind'] == 'containers_digest':
            run_insight_digest(cfg, cfg['id'], results)
    return results


# ─────────────────────────────── phase 6 ─────────────────────────────────
# agent NLQ: same questions/goldens as phase 4, but the filter group must come
# from the agent (POST /ai-agent/ask {question, mode:"nlq"} -> nlq_filters).

def contract_probe(phase: int) -> str | None:
    """One cheap canary call per pending-suite phase. Returns None when the
    agent implements the suite contract, else a reason string."""
    try:
        if phase == 6:
            r = agent_post('ask', {'question': 'probe', 'mode': 'nlq'})
            if 'nlq_filters' not in r:
                return 'contract missing: response has no nlq_filters'
        elif phase == 7:
            r = agent_post('sessions', {})
            if not r.get('id'):
                return 'contract missing: POST /ai-agent/sessions returned no id'
        elif phase == 8:
            r = agent_post('transform', {
                'bundle': {'type': 'bundle', 'objects': [{'type': 'malware', 'name': 'ProbeX'}]},
                'operation': 'refine_description'})
            if 'bundle' not in r:
                return 'contract missing: response has no bundle'
        elif phase == 9:
            r = agent_post('ask', {'question': 'probe', 'mode': 'extract',
                                            'text': 'IOC: 192.0.2.1'})
            if 'indicators' not in r:
                return 'contract missing: response has no indicators'
    except PendingEndpoint as e:
        return str(e)
    return None


def pending_results(phase: int, cases: list, reason: str) -> list:
    return [{'case': c.get('id', c.get('kind', '?')), 'phase': phase,
             'status': 'SKIP-PENDING', 'score': 0.0, 'checks': [],
             'error': reason[:300], 'output': ''} for c in cases]


def run_phase6():
    contract = json.load(open(CASES_V2 / 'agent_nlq.json'))
    cases = [c for c in load_case_files('nlq') if c.get('suite', 'regression') in SUITES]
    reason = contract_probe(6)
    if reason:
        return pending_results(6, cases, reason)
    results = []
    for c in cases:
        checks = []
        try:
            art = agent_post(contract['endpoint_contract']['url'].lstrip('/'),
                             {'question': c['question'], 'mode': 'nlq'})
            filters = art.get('nlq_filters')
            checks.append(check('filters-produced', bool(filters and filters.get('filters')),
                                str(filters)[:150]))
            golden_names = set(c.get('golden_names') or [])
            metrics = {'jaccard': None, 'precision': None, 'recall': None, 'exact_match': None,
                       'result_count': None}
            if filters and golden_names:
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
                    exact = got == golden_names
                    metrics.update({'jaccard': round(j, 4), 'precision': round(prec, 4),
                                    'recall': round(rec, 4), 'exact_match': exact,
                                    'result_count': len(got)})
                    checks.append(check(f'jaccard>={CFG["nlq_threshold"]}', j >= CFG['nlq_threshold'],
                                        f'j={j:.2f} p={prec:.2f} r={rec:.2f}'))
                    if CFG['strict']:
                        checks.append(check('exact-match', exact, f'got={len(got)} gold={len(golden_names)}'))
        except PendingEndpoint as e:
            results.append({'case': c['id'], 'phase': 6, 'status': 'SKIP-PENDING', 'score': 0.0,
                            'checks': [], 'error': str(e)[:300], 'output': ''})
            continue
        except Exception as e:  # noqa: BLE001
            results.append({'case': c['id'], 'phase': 6, 'status': 'ERROR', 'score': 0.0,
                            'checks': [], 'error': str(e)[:300], 'output': ''})
            continue
        results.append({'case': c['id'], 'phase': 6, 'status': 'OK',
                        'score': case_score(checks), 'checks': checks,
                        'metrics': metrics, 'output': str(filters)[:300]})
        time.sleep(1)
    return results


# ─────────────────────────────── phase 7 ─────────────────────────────────
# local chat sessions: functional contract (create/persist/isolate/history/delete)

def run_phase7():
    cfgs = load_v2('chat_sessions')
    reason = contract_probe(7)
    if reason:
        return pending_results(7, cfgs, reason)
    results = []
    nonce = next((c['nonce'] for c in cfgs if c['kind'] == 'persist'), 'BRICK7-KILO-347')

    def add(case_id, checks):
        results.append({'case': case_id, 'phase': 7, 'status': 'OK',
                        'score': case_score(checks), 'checks': checks, 'output': ''})

    def pend(case_id, e):
        results.append({'case': case_id, 'phase': 7, 'status': 'SKIP-PENDING', 'score': 0.0,
                        'checks': [], 'error': str(e)[:300], 'output': ''})

    s1 = s2 = None
    # create + persist
    try:
        s1 = agent_post('sessions', {}).get('id')
        a0 = agent_post('ask', {
            'question': f'Remember this code: {nonce}. Reply with OK only.', 'session_id': s1})
        a1 = agent_post('ask', {
            'question': 'What code did I ask you to remember? Reply with just the code.',
            'session_id': s1})
        add('chat-create-persist', [
            check('session-created', bool(s1), f'id={s1}'),
            check('first-ack', len(a0.get('answer', '')) <= 60, a0.get('answer', '')[:60]),
            check('nonce-persisted', nonce in a1.get('answer', ''), a1.get('answer', '')[:120]),
        ])
    except PendingEndpoint as e:
        pend('chat-create-persist', e)
    except Exception as e:  # noqa: BLE001
        results.append({'case': 'chat-create-persist', 'phase': 7, 'status': 'ERROR',
                        'score': 0.0, 'checks': [], 'error': str(e)[:300], 'output': ''})

    # isolation: fresh session must not leak the nonce
    try:
        s2 = agent_post('sessions', {}).get('id')
        a2 = agent_post('ask', {
            'question': 'What code did I ask you to remember? Reply with just the code.',
            'session_id': s2})
        add('chat-isolation', [check('no-cross-session-leak', nonce not in a2.get('answer', ''),
                                     a2.get('answer', '')[:120])])
    except PendingEndpoint as e:
        pend('chat-isolation', e)
    except Exception as e:  # noqa: BLE001
        results.append({'case': 'chat-isolation', 'phase': 7, 'status': 'ERROR',
                        'score': 0.0, 'checks': [], 'error': str(e)[:300], 'output': ''})

    # history ordering
    try:
        h = agent_get(f'sessions/{s1}').json()
        msgs = h.get('messages', [])
        roles = [m.get('role') for m in msgs]
        contents = ' '.join(m.get('content', '') for m in msgs)
        add('chat-history-order', [
            check('messages-present', len(msgs) >= 4, f'n={len(msgs)}'),
            check('roles-alternate', roles[:2] == ['user', 'assistant'], str(roles[:4])),
            check('order-user-first', roles and roles[0] == 'user', str(roles[:2])),
            check('nonce-in-history', nonce in contents, ''),
        ])
    except PendingEndpoint as e:
        pend('chat-history-order', e)
    except Exception as e:  # noqa: BLE001
        results.append({'case': 'chat-history-order', 'phase': 7, 'status': 'ERROR',
                        'score': 0.0, 'checks': [], 'error': str(e)[:300], 'output': ''})

    # list
    try:
        listing = agent_get('sessions').json()
        ids = [s.get('id') for s in listing] if isinstance(listing, list) else []
        add('chat-list', [
            check('is-list', isinstance(listing, list), type(listing).__name__),
            check('contains-live-sessions', s2 in ids or s1 in ids, f'{len(ids)} sessions'),
        ])
    except PendingEndpoint as e:
        pend('chat-list', e)
    except Exception as e:  # noqa: BLE001
        results.append({'case': 'chat-list', 'phase': 7, 'status': 'ERROR',
                        'score': 0.0, 'checks': [], 'error': str(e)[:300], 'output': ''})

    # delete + verify gone
    try:
        code = agent_delete(f'sessions/{s1}')
        gone = False
        try:
            resp = agent_get(f'sessions/{s1}')
            gone = resp.status_code == 404 or not (resp.json().get('messages') or [])
        except Exception:  # noqa: BLE001
            gone = True
        add('chat-delete', [
            check('delete-accepted', code in (200, 202, 204), f'code={code}'),
            check('session-gone', gone, ''),
        ])
    except PendingEndpoint as e:
        pend('chat-delete', e)
    except Exception as e:  # noqa: BLE001
        results.append({'case': 'chat-delete', 'phase': 7, 'status': 'ERROR',
                        'score': 0.0, 'checks': [], 'error': str(e)[:300], 'output': ''})

    # streaming (SSE) — chunked delivery of the same /ask contract
    try:
        import requests as _rq
        from lib import AGENT_URL as _AU
        url = _AU.rstrip('/') + '/ask'
        res = _rq.post(url, json={'question': 'One-sentence overview of APT28.', 'stream': True},
                       timeout=120, stream=True)
        if res.status_code in (404, 501, 503):
            raise PendingEndpoint(f'/ask stream -> HTTP {res.status_code}')
        if res.status_code >= 400:
            raise RuntimeError(f'/ask stream -> HTTP {res.status_code}')
        ctype = res.headers.get('content-type', '')
        deltas, raw_events = [], 0
        for line in res.iter_lines(decode_unicode=True):
            if not line or not line.startswith('data:'):
                continue
            payload = line[5:].strip()
            if payload == '[DONE]':
                break
            raw_events += 1
            try:
                evt = json.loads(payload)
                if evt.get('delta'):
                    deltas.append(evt['delta'])
            except json.JSONDecodeError:
                deltas.append(payload)
        text = ''.join(deltas)
        add('chat-streaming', [
            check('sse-content-type', ctype.startswith('text/event-stream'), ctype),
            check('chunked>=2', raw_events >= 2, f'{raw_events} events'),
            check('reassembled-nonempty', len(text) > 40, f'len={len(text)}'),
            check('no-null-garbage', not NULL_GARBAGE.search(text), ''),
        ])
    except PendingEndpoint as e:
        pend('chat-streaming', e)
    except Exception as e:  # noqa: BLE001
        results.append({'case': 'chat-streaming', 'phase': 7, 'status': 'ERROR',
                        'score': 0.0, 'checks': [], 'error': str(e)[:300], 'output': ''})
    return results


# ─────────────────────────────── phase 8 ─────────────────────────────────
# playbook transform/send: STIX bundle contract over the agent

def build_bundle(cfg: dict) -> dict:
    src = cfg['bundle_from']
    if 'fixture' in src:
        fx = json.load(open(Path(__file__).parent / 'gold_graph' / 'fixture.json'))
        objects = [{'type': e['type'], 'name': e['display_name'],
                    'description': e.get('description', '')} for e in fx['entities']]
        names = {e['key']: e['display_name'] for e in fx['entities']}
        for r in fx['relations']:
            objects.append({'type': 'relationship', 'relationship_type': r['type'],
                            'source_ref': names[r['from']], 'target_ref': names[r['to']]})
        return {'type': 'bundle', 'objects': objects}
    snapshot = json.load(open(Path(__file__).parent / 'data' / 'otx-snapshot-2026-09-16.json'))
    objs = snapshot['objects']
    report = next(o for o in objs if o['type'] == 'report')
    refs = set(report.get('object_refs', []))
    sub = [report] + [o for o in objs if o.get('id') in refs]
    return {'type': 'bundle', 'objects': sub}


def bundle_entity_names(bundle: dict) -> set:
    names = set()
    for o in bundle.get('objects', []):
        if o.get('name'):
            names.add(o['name'])
        if o.get('pattern'):  # indicator objects carry the pattern as identity
            names.add(o['pattern'])
    return names


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def run_phase8():
    cfgs = load_v2('playbook')
    reason = contract_probe(8)
    if reason:
        return pending_results(8, cfgs, reason)
    results = []
    for cfg in cfgs:
        checks = []
        try:
            bundle = build_bundle(cfg)
            before = platform_object_count()
            if cfg['kind'] == 'transform':
                in_names = bundle_entity_names(bundle)
                out1 = agent_post('transform',
                                  {'bundle': bundle, 'operation': cfg['operation']})
                out2 = agent_post('transform',
                                  {'bundle': bundle, 'operation': cfg['operation']})
                ob = out1.get('bundle') or {}
                out_names = bundle_entity_names(ob)
                in_types = {o.get('type') for o in bundle['objects']}
                out_types = {o.get('type') for o in ob.get('objects', [])}
                preservation = len(in_names & out_names) / max(len(in_names), 1)
                ref_names = {r for o in bundle['objects']
                             for r in (o.get('source_ref'), o.get('target_ref')) if r}
                allowed_names = in_names | ref_names
                strays = out_names - allowed_names
                checks = [
                    check('valid-bundle', ob.get('type') == 'bundle' and isinstance(ob.get('objects'), list)
                          and len(ob['objects']) > 0, f'objects={len(ob.get("objects", []))}'),
                    check('entity-preservation>=1.0', preservation >= 1.0, f'{preservation:.2f}'),
                    check('no-hallucinated-entities', not strays, f'strays={sorted(strays)[:4]}'),
                    check('type-whitelist', out_types <= in_types, f'new={sorted(out_types - in_types)[:4]}'),
                    check('deterministic', canonical(ob) == canonical(out2.get('bundle') or {}),
                          'two calls must hash-equal'),
                ]
            else:  # send (consumer analysis)
                names = sorted(bundle_entity_names(bundle))
                art = agent_post('ask', {
                    'question': 'Analyze this bundle: list the key entities and their relations.',
                    'mode': 'analyze_bundle',
                    'bundle': {'names': names[:60]}})
                cited = set(art.get('cited_entity_names') or [])
                allowed = set(names) | {o.get('source_ref') or o.get('target_ref')
                                        for o in bundle['objects']}
                strays = {c for c in cited if c not in allowed}
                checks = [
                    check('cited-min', len(cited) >= cfg.get('min_cited', 4), f'{len(cited)} cited'),
                    check('no-external-entities', not strays, f'strays={sorted(strays)[:4]}'),
                ]
            after = platform_object_count()
            checks.append(check('platform-readonly', before == after, f'{before} -> {after}'))
        except PendingEndpoint as e:
            results.append({'case': cfg['id'], 'phase': 8, 'status': 'SKIP-PENDING', 'score': 0.0,
                            'checks': [], 'error': str(e)[:300], 'output': ''})
            continue
        except Exception as e:  # noqa: BLE001
            results.append({'case': cfg['id'], 'phase': 8, 'status': 'ERROR', 'score': 0.0,
                            'checks': [], 'error': str(e)[:300], 'output': ''})
            continue
        results.append({'case': cfg['id'], 'phase': 8, 'status': 'OK',
                        'score': case_score(checks), 'checks': checks, 'output': ''})
    return results


# ─────────────────────────────── phase 9 ─────────────────────────────────
# file -> STIX: frozen CISA advisories (official STIX gold) + gold-graph narrative

IOC_RX = [
    (re.compile(r'\b[a-f0-9]{64}\b', re.I), "file:hashes.'SHA-256'"),
    (re.compile(r'\b[a-f0-9]{40}\b', re.I), "file:hashes.'SHA-1'"),
    (re.compile(r'\b[a-f0-9]{32}\b', re.I), "file:hashes.'MD5'"),
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}/\S+'), 'url'),
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), 'ipv4-addr'),
    (re.compile(r'\b[\w-]{2,}(?:\.[\w-]{2,})*\.(?:com|net|org|io|xyz|info|ru|cf|biz|top|online|site|icu|club|us|uk)\b', re.I), 'domain-name'),
    (re.compile(r'\bhttps?://\S+'), 'url'),
]


def ioc_kind(value: str) -> str | None:
    v = value.strip()
    if re.fullmatch(r'[a-f0-9]{64}', v, re.I):
        return "file:hashes.'SHA-256'"
    if re.fullmatch(r'[a-f0-9]{40}', v, re.I):
        return "file:hashes.'SHA-1'"
    if re.fullmatch(r'[a-f0-9]{32}', v, re.I):
        return "file:hashes.'MD5'"
    if re.match(r'https?://', v, re.I):
        return 'url'
    if re.fullmatch(r'(?:\d{1,3}\.){3}\d{1,3}/\S*', v):
        return 'url'
    if re.fullmatch(r'(?:\d{1,3}\.){3}\d{1,3}', v):
        return 'ipv4-addr'
    if re.fullmatch(r'[\w-]{2,}(?:\.[\w-]{2,})*', v, re.I):
        return 'domain-name'
    return None


def text_ioc_universe(text: str) -> set:
    """All IOC-shaped values present in the source text (grounding universe).

    The text is normalized (refang + unicode dashes) BEFORE matching — same
    contract as the agent's extractor, so both sides agree on values."""
    normalized = refang(re.sub(r'[\u2010\u2011\u2012\u2013\u2014]', '-', text or ''))
    found = set()
    for rx, _ in IOC_RX:
        for m in rx.findall(normalized):
            found.add(m.lower())
    return found


def run_phase9():
    cfgs = load_v2('file2stix')
    reason = contract_probe(9)
    if reason:
        return pending_results(9, cfgs, reason)
    results = []
    for cfg in cfgs:
        checks = []
        try:
            if cfg['kind'] == 'cisa':
                base = Path(__file__).parent / 'data' / 'cisa'
                text = (base / f'{cfg["advisory"]}.txt').read_text()
                gold = json.load(open(base / f'{cfg["advisory"]}_gold.json'))
                gold_vals = {v.lower() for v in gold['ioc_values']}
                art = agent_post('ask', {'mode': 'extract', 'text': text})
                inds = art.get('indicators') or []
                out_vals = {refang(i.get('value', '')).lower() for i in inds if i.get('value')}
                rec = len(out_vals & gold_vals) / max(len(gold_vals), 1)
                universe = gold_vals | text_ioc_universe(text)
                strays = out_vals - universe
                hall = len(strays) / max(len(out_vals), 1)
                techs_out = {t.strip().upper() for t in (art.get('techniques') or [])}
                tech_gold = {t.upper() for t in gold['technique_gold']}
                trec = len(techs_out & tech_gold) / max(len(tech_gold), 1)
                bad_types = [i for i in inds if i.get('stix_type')
                             and i.get('stix_type') != ioc_kind(refang(i.get('value', '')))]
                checks = [
                    check(f'ioc-recall>={cfg["ioc_recall_gate"]}', rec >= cfg['ioc_recall_gate'],
                          f'{len(out_vals & gold_vals)}/{len(gold_vals)}={rec:.2f}'),
                    check(f'ioc-hallucination<={cfg["hallucination_gate"]}', hall <= cfg['hallucination_gate'],
                          f'strays={sorted(strays)[:4]}'),
                    check(f'technique-recall>={cfg["technique_recall_gate"]}',
                          trec >= cfg['technique_recall_gate'], f'{trec:.2f}'),
                    check('type-validity', not bad_types, f'bad={bad_types[:3]}'),
                ]
            else:  # narrative
                art = agent_post('ask', {'mode': 'extract', 'text': cfg['text']})
                ents = [e.strip() for e in (art.get('entities') or []) if e.strip()]
                rels = {(r[0].strip(), r[1].strip().replace(' ', '-'), r[2].strip())
                        for r in (art.get('relations') or []) if len(r) == 3}
                gold_ents = set(cfg['entity_gold'])
                gold_rels = {tuple(r) for r in cfg['relation_gold']}
                ent_set = set(ents)
                decoys_hit = sorted(ent_set & set(cfg['decoy_names']))
                rec = len(ent_set & gold_ents) / max(len(gold_ents), 1)
                rrec = len(rels & gold_rels) / max(len(gold_rels), 1)
                strays = ent_set - gold_ents - set(cfg['decoy_names'])
                checks = [
                    check(f'entity-recall>={cfg["entity_recall_gate"]}', rec >= cfg['entity_recall_gate'],
                          f'{len(ent_set & gold_ents)}/{len(gold_ents)}={rec:.2f}'),
                    check(f'relation-recall>={cfg["relation_recall_gate"]}', rrec >= cfg['relation_recall_gate'],
                          f'{len(rels & gold_rels)}/{len(gold_rels)}={rrec:.2f}'),
                    check('decoys-excluded', len(decoys_hit) <= cfg.get('decoy_max', 0),
                          f'decoys={decoys_hit}'),
                    check('no-hallucinated-entities', len(strays) <= 2, f'strays={sorted(strays)[:4]}'),
                ]
        except PendingEndpoint as e:
            results.append({'case': cfg['id'], 'phase': 9, 'status': 'SKIP-PENDING', 'score': 0.0,
                            'checks': [], 'error': str(e)[:300], 'output': ''})
            continue
        except Exception as e:  # noqa: BLE001
            results.append({'case': cfg['id'], 'phase': 9, 'status': 'ERROR', 'score': 0.0,
                            'checks': [], 'error': str(e)[:300], 'output': ''})
            continue
        results.append({'case': cfg['id'], 'phase': 9, 'status': 'OK',
                        'score': case_score(checks), 'checks': checks, 'output': ''})
        time.sleep(1)
    return results


# ─────────────────────────────── phase 10 ────────────────────────────────
# agent reports: threat report generation + indicator -> STIX pattern conversion
# (replaces the SDL-only, resolver-less platform mutations)

def run_phase10():
    results = []
    tasks = {t['id']: t for t in json.load(open(Path(__file__).parent / 'agent_bench' / 'tasks.json'))}
    for cfg in load_v2('agent_reports'):
        checks = []
        try:
            if cfg['kind'] == 'threat_report':
                gold = set(next(t for t in tasks.values()
                                if t['id'].startswith('t1-'))['gold_entity_names'])
                art = agent_post('ask', {
                    'question': f'Generate a complete threat intelligence report on {cfg["target"]}: '
                                'overview, tools and malware used, attack techniques, mitigations. '
                                'Use markdown headings.',
                    'mode': 'report'})
                ans = art.get('answer') or ''
                hit = sum(1 for g in gold if g.lower() in ans.lower())
                rec = hit / max(len(gold), 1)
                headings = len(re.findall(r'^#{1,4} ', ans, re.M)) + len(re.findall(r'\n[A-Z][A-Za-z ]{4,40}:\n', ans))
                checks = [
                    check('entity-recall>=0.5', rec >= 0.5, f'{hit}/{len(gold)}={rec:.2f}'),
                    check('min-length', len(ans) > 1500, f'len={len(ans)}'),
                    check('structure-headings>=3', headings >= 3, f'{headings}'),
                    check('no-null-garbage', not NULL_GARBAGE.search(ans), ''),
                    check('no-error', not ans.startswith('An error occurred'), ans[:80]),
                ]
            elif cfg['kind'] == 'victim_report':
                d = gql('query S($name: String) { sectors(first: 5, search: $name) { edges { node { id name } } } }',
                        {'name': cfg['target']})
                if not any(e['node']['name'] == cfg['target'] for e in d['sectors']['edges']):
                    results.append({'case': cfg['id'], 'phase': 10, 'status': 'SKIP-ENV', 'score': 0.0,
                                    'checks': [], 'error': 'victim sector not imported (gold graph fixture v1.1)',
                                    'output': ''})
                    continue
                art = agent_post('ask', {
                    'question': f'Generate a victim-focused intelligence report on the {cfg["target"]} sector, '
                                'grounded in the knowledge graph: which threat actors or campaigns target it, '
                                'their malware and tools, and recommended mitigations. Use markdown headings.',
                    'mode': 'report'})
                ans = art.get('answer') or ''
                headings = len(re.findall(r'^#{1,4} ', ans, re.M)) + len(re.findall(r'\n[A-Z][A-Za-z ]{4,40}:\n', ans))
                attributors = ('gold alpha', 'operation goldrush')
                checks = [
                    check('mentions-entity', cfg['target'].lower() in ans.lower(), cfg['target']),
                    check('victim-attribution', any(a in ans.lower() for a in attributors),
                          f'found={[a for a in attributors if a in ans.lower()]}'),
                    check('min-length', len(ans) > 800, f'len={len(ans)}'),
                    check('structure-headings>=3', headings >= 3, f'{headings}'),
                    check('no-null-garbage', not NULL_GARBAGE.search(ans), ''),
                    check('no-error', not ans.startswith('An error occurred'), ans[:80]),
                ]
            else:  # indicator_convert
                snap = json.load(open(Path(__file__).parent / 'data' / 'otx-snapshot-2026-09-16.json'))
                inds = sorted((o for o in snap['objects']
                               if o['type'] == 'indicator' and "'SHA-256'" in (o.get('pattern') or '')),
                              key=lambda o: o['pattern'])[:cfg.get('indicator_count', 3)]
                wanted = {o['pattern']: re.search(r"'SHA-256' = '([a-f0-9]{64})'", o['pattern']).group(1)
                          for o in inds}
                art = agent_post('ask', {
                    'question': 'Convert each of these file-hash indicators into a STIX 2.1 pattern. '
                                'Input: ' + ', '.join(wanted.values()),
                    'mode': 'convert'})
                pats = art.get('patterns') or re.findall(r"\[file:hashes\.'SHA-256'\s*=\s*'([a-f0-9]{64})'\]",
                                                         art.get('answer') or '')
                if pats and isinstance(pats[0], str) and not pats[0].startswith('['):
                    pats = [f"[file:hashes.'SHA-256' = '{p.lower()}']" for p in pats]
                out_vals = {re.search(r"'([a-f0-9]{64})'", p).group(1).lower()
                            for p in pats if re.search(r"'([a-f0-9]{64})'", p)}
                gold_vals_l = {v.lower() for v in wanted.values()}
                valid = all(re.fullmatch(r"\[file:hashes\.'SHA-256' = '[a-f0-9]{64}'\]", p, re.I)
                            for p in pats) if pats else False
                checks = [
                    check('pattern-valid', bool(pats) and valid, f'{len(pats)} patterns'),
                    check('value-preserved', out_vals == gold_vals_l,
                          f'{len(out_vals & gold_vals_l)}/{len(wanted)}'),
                    check('type-correct', all("file:hashes.'SHA-256'" in p for p in pats), ''),
                    check('no-extra-values', out_vals <= gold_vals_l,
                          f'extra={len(out_vals - gold_vals_l)}'),
                ]
        except PendingEndpoint as e:
            results.append({'case': cfg['id'], 'phase': 10, 'status': 'SKIP-PENDING', 'score': 0.0,
                            'checks': [], 'error': str(e)[:300], 'output': ''})
            continue
        except Exception as e:  # noqa: BLE001
            results.append({'case': cfg['id'], 'phase': 10, 'status': 'ERROR', 'score': 0.0,
                            'checks': [], 'error': str(e)[:300], 'output': ''})
            continue
        results.append({'case': cfg['id'], 'phase': 10, 'status': 'OK',
                        'score': case_score(checks), 'checks': checks,
                        'output': (art.get('answer') or '')[:300] if isinstance(art, dict) else ''})
        time.sleep(1)
    return results


# ─────────────────────────────── main ────────────────────────────────────

RUNNERS = {1: run_phase1, 2: run_phase2, 3: run_phase3, 4: run_phase4, 5: run_phase5,
           6: run_phase6, 7: run_phase7, 8: run_phase8, 9: run_phase9, 10: run_phase10}
CFG = {'nlq_threshold': 0.3, 'strict': False}
SUITES = {'regression'}


def main():
    global SUITES
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', type=int, choices=sorted(RUNNERS))
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--suite', choices=['regression', 'heldout', 'all'], default='regression',
                    help='regression = frozen v1 contract (default); held-out cases must never tune prompts/tools')
    ap.add_argument('--nlq-threshold', type=float, default=0.3,
                    help='Jaccard gate for NLQ (0.3 is a smoke threshold; 0.8 for acceptance runs)')
    ap.add_argument('--strict', action='store_true',
                    help='NLQ exact result-set match becomes a gating check')
    args = ap.parse_args()
    CFG['nlq_threshold'] = args.nlq_threshold
    CFG['strict'] = args.strict
    SUITES = {'regression', 'heldout'} if args.suite == 'all' else {args.suite}
    phases = sorted(RUNNERS) if args.all else [args.phase]
    if not phases:
        ap.error('nothing to run: pass --phase N or --all')
    all_results = []
    for p in phases:
        print(f'── phase {p} ({PHASE_NAMES[p]}) [suite={args.suite}] …', flush=True)
        all_results.extend(RUNNERS[p]())

    scores = {}
    for p in phases:
        rs = [r for r in all_results if r['phase'] == p]
        ok = [r['score'] for r in rs if r['status'] == 'OK']
        skipped = sum(1 for r in rs if r['status'] == 'SKIP-EE')
        env = sum(1 for r in rs if r['status'] == 'SKIP-ENV')
        pending = sum(1 for r in rs if r['status'] == 'SKIP-PENDING')
        scores[p] = {
            'category': PHASE_NAMES[p],
            'cases': len(rs),
            'executed': len(rs) - skipped - pending - env,
            'skipped_ee': skipped,
            'skipped_pending': pending,
            'skipped_env': env,
            'check_pass_rate': round(sum(ok) / len(ok), 2) if ok else 0.0,
            'passed_avg': round(sum(ok) / len(ok), 2) if ok else 0.0,  # v1-compat alias
            'status': ('OK' if all(r['status'] == 'OK' for r in rs)
                       else 'PENDING' if all(r['status'] == 'SKIP-PENDING' for r in rs)
                       else 'SKIP-ENV' if all(r['status'] == 'SKIP-ENV' for r in rs)
                       else 'PARTIAL' if any(r['status'] == 'OK' for r in rs)
                       else rs[0]['status']),
        }

    lines = ['# AI Benchmark Report', '',
             f'_generated: {time.strftime("%Y-%m-%d %H:%M:%S")}_ '
             f'(suite={args.suite}, nlq_threshold={args.nlq_threshold}, strict={args.strict})_', '',
             '> Scores are **check pass rates**: the share of deterministic checks a case passed. '
             'Per-metric precision/recall/exact-match are reported separately in metrics. '
             'SKIP-PENDING cases gate features not implemented yet and are excluded from pass rates.', '']
    for p, s in scores.items():
        lines.append(f"## Phase {p} — {s['category']}: **{s['check_pass_rate']}** ({s['status']})"
                     f" — executed {s['executed']}/{s['cases']}, SKIP-EE {s['skipped_ee']},"
                     f" SKIP-PENDING {s['skipped_pending']}, SKIP-ENV {s['skipped_env']}")
        for r in (x for x in all_results if x['phase'] == p):
            lines.append(f"- `{r['case']}` {r['status']} score={r['score']:.2f}")
            if r.get('metrics'):
                m = {k: v for k, v in r['metrics'].items() if k not in ('raw_filter', 'final_filter')}
                lines.append(f"  - metrics: {json.dumps(m)[:300]}")
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
