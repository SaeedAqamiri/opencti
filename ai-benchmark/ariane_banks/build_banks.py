"""Build the two Ariane benchmark question banks (112 questions each):
  Bank A (all-data)   -> all_data_112.csv
  Bank B (alienvault) -> alienvault_only_112.csv
Ranks 1-100: discovery/investigation questions sorted hardest (L3) -> easiest (L1),
agentic categories first within a level. Ranks 101-112: the WRK (write/action) block,
appended in authored order (approve/deny twin pairs share a scenario; the only variable
is the evaluator's approve/deny at the approval gate).
Outputs: CSV (utf-8-sig for Excel + Persian), XLSX (two filtered sheets), JSON mirror.
"""
import csv, json, sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import bank_all_data
import bank_alienvault

CATEGORY_ORDER = ['AGT', 'SAF', 'NLQ', 'INS', 'RPT', 'CHAT', 'PLB', 'F2S', 'TXT']
LEVEL_ORDER = {'L3': 0, 'L2': 1, 'L1': 2}

COLUMNS = ['rank', 'id', 'category', 'category_label', 'ariane_surface', 'surface_tech', 'gated',
           'difficulty', 'hops', 'question_en', 'question_fa', 'input_entity_or_ioc',
           'expected_answer_type', 'golden_hint', 'grading_suggestion', 'refusal_probe',
           'write_action', 'approval_gate', 'deny_twin_of', 'fixture', 'cleanup_step', 'notes']


def refusal_of(q):
    en = q['en'].lower()
    if q['cat'] == 'SAF' or q.get('wa') == 'none' and q['cat'] == 'WRK' or 'refus' in en or 'must refuse' in en or 'delete' in en:
        return 'Y'
    return 'N'


def base_row(q, cat):
    return {
        'category': q['cat'],
        'category_label': cat[0],
        'ariane_surface': cat[0],
        'surface_tech': q.get('tech', cat[1]),
        'gated': q.get('gated', cat[2]),
        'difficulty': q['d'],
        'hops': q['hops'],
        'question_en': q['en'].strip(),
        'question_fa': q['fa'].strip(),
        'input_entity_or_ioc': q['inp'].strip(),
        'expected_answer_type': q['ans'].strip(),
        'golden_hint': q['gold'].strip(),
        'grading_suggestion': q['grad'].strip(),
        'refusal_probe': refusal_of(q),
    }


def build(questions, bank, prefix):
    core = [q for q in questions if not q.get('wrk')]
    wrk = [q for q in questions if q.get('wrk')]
    rows = []
    for i, q in enumerate(sorted(core, key=lambda q: (LEVEL_ORDER[q['d']], CATEGORY_ORDER.index(q['cat']))), 1):
        cat = bank_all_data.CATS[q['cat']]
        rows.append({'rank': i, 'id': f'{prefix}-{i:03d}', **base_row(q, cat),
                     'write_action': 'none', 'approval_gate': 'N', 'deny_twin_of': '',
                     'fixture': '', 'cleanup_step': '',
                     'notes': f'bank={bank}; scope={"createdBy=AlienVault only" if bank == "alienvault" else "whole platform"}'})
    # WRK block: authored order, ranks 101-112; resolve deny twins after ids exist
    wrk_rows = []
    twin_id = {}
    for j, q in enumerate(wrk, 101):
        cat = bank_all_data.CATS[q['cat']]
        wrk_rows.append({'rank': j, 'id': f'{prefix}-{j:03d}', **base_row(q, cat),
                         'write_action': q.get('wa', 'none'), 'approval_gate': q.get('gate', 'N'),
                         'deny_twin_of': '', 'fixture': q.get('fixture', ''),
                         'cleanup_step': q.get('cleanup', ''),
                         'notes': f'bank={bank}; scope=scratch fixtures only; '
                                  f'gate=chatbot pending-approvals/approve; {"pending-agent-v2" if q.get("gate") == "Y" else "executable now"}'})
        if q.get('twin'):
            twin_id[q['twin']] = f'{prefix}-{j:03d}'
    for r in wrk_rows:
        key = r['id']
        scen = key[-3:]
    # map deny twin -> approve twin id (same scenario letter)
    for q, r in zip(wrk, wrk_rows):
        t = q.get('twin', '')
        if t.endswith('d'):
            r['deny_twin_of'] = twin_id.get(t[:-1] + 'a', '')
    rows += wrk_rows
    return rows


def validate(rows, name):
    from collections import Counter
    assert len(rows) == 112, f'{name}: {len(rows)} rows'
    cats = Counter(r['category'] for r in rows)
    agentic = cats['AGT'] + cats['SAF']
    assert agentic >= 50, f'{name}: agentic={agentic}'
    assert cats['WRK'] == 12, f'{name}: WRK={cats["WRK"]}'
    assert len({r['id'] for r in rows}) == 112
    assert all(r['question_en'] and r['question_fa'] for r in rows)
    twins = {r['id']: r['deny_twin_of'] for r in rows if r['deny_twin_of']}
    assert all(t in {r['id'] for r in rows} for t in twins.values()), 'dangling twin refs'
    print(f'{name}: 112 rows | AGT={cats["AGT"]} SAF={cats["SAF"]} (agentic {agentic}%) '
          f'WRK={cats["WRK"]} NLQ={cats["NLQ"]} INS={cats["INS"]} RPT={cats["RPT"]} TXT={cats["TXT"]} '
          f'F2S={cats["F2S"]} PLB={cats["PLB"]} CHAT={cats["CHAT"]} | '
          f'L3={sum(1 for r in rows if r["difficulty"]=="L3")} '
          f'L2={sum(1 for r in rows if r["difficulty"]=="L2")} '
          f'L1={sum(1 for r in rows if r["difficulty"]=="L1")} | '
          f'approval_gates={sum(1 for r in rows if r["approval_gate"]=="Y")} '
          f'refusal_probes={sum(1 for r in rows if r["refusal_probe"]=="Y")}')


def main():
    a = build(bank_all_data.QUESTIONS, 'all-data', 'ALL')
    b = build(bank_alienvault.QUESTIONS, 'alienvault', 'AV')
    validate(a, 'all-data')
    validate(b, 'alienvault')

    outdir = HERE.parent / 'ariane_question_banks'
    outdir.mkdir(exist_ok=True)

    for rows, name in ((a, 'all_data_112'), (b, 'alienvault_only_112')):
        with open(outdir / f'{name}.csv', 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        # keep legacy 100-row names in sync is not needed; 112 supersedes

    with open(outdir / 'question_banks.json', 'w', encoding='utf-8') as f:
        json.dump({'all_data': a, 'alienvault_only': b}, f, ensure_ascii=False, indent=1)

    try:
        import openpyxl
        wb = openpyxl.Workbook()
        for rows, name in ((a, 'All-Data (112)'), (b, 'AlienVault-Only (112)')):
            ws = wb.create_sheet(name[:31])
            ws.append(COLUMNS)
            for r in rows:
                ws.append([r[c] for c in COLUMNS])
            ws.freeze_panes = 'A2'
            ws.auto_filter.ref = ws.dimensions
        wb.remove(wb.active)
        wb.save(outdir / 'ariane_question_banks.xlsx')
        print('xlsx: written')
    except ImportError:
        print('xlsx: openpyxl missing — CSV+JSON only')

    # remove stale 100-row artifacts if present
    for stale in ('all_data_100.csv', 'alienvault_only_100.csv'):
        p = outdir / stale
        if p.exists():
            p.unlink()
            print('removed stale', stale)
    print('done ->', outdir)


if __name__ == '__main__':
    main()
