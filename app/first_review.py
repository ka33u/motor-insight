"""Versioned synthetic review declarations; never production release authority."""
from collections import Counter, defaultdict
from pathlib import Path
import re
from . import first_piece, metrology
from .first_review_schema import DATASET
STATES = {'none': '无生效复核', 'matched': '登记通过且依据相符', 'held': '登记不予通过',
          'pending': '登记待补充', 'stale': '依据变化待重核', 'withdrawn': '复核登记已撤销',
          'invalid': '复核资料待核对', 'contradicted': '通过结论与证据不符'}
NOTICE = '合成Excel复核登记，不是电子签名或正式生产批准。复核依据按当前导入事实重放，摘要一致不证明历史数据库未被改写；原件、测量能力、批次触发覆盖和正式放量仍需授权流程。'


def issues(row):
    out = []
    def add(field, text):
        out.append(dict(code='FIRST_REVIEW', field=field, message=text))
    if type(row.get('version')) is not int or row['version'] < 1:
        add('version', '复核版本须为正整数')
    if row.get('version') == 1 and row.get('previous_id') or type(row.get('version')) is int and row['version'] > 1 and not row.get('previous_id'):
        add('previous_id', '首版不引用前版；后续版本须引用前版')
    if row.get('status') not in ('草稿', '已登记', '撤销'):
        add('status', '登记状态无效')
    if row.get('decision') not in ('复核通过', '不予通过', '待补充'):
        add('decision', '登记结论无效')
    if row.get('decision') == '复核通过' and not row.get('check_id'):
        add('check_id', '通过结论须明确检验记录')
    for f in ('basis_hash', 'rule_hash'):
        if not isinstance(row.get(f), str) or not re.fullmatch('[0-9a-f]{64}', row[f]):
            add(f, '摘要须为64位小写十六进制文本')
    clocks = [metrology.clock(row.get(k)) for k in ('basis_at', 'reviewed', 'registered')]
    if not all(clocks) or all(clocks) and not clocks[0] <= clocks[1] <= clocks[2]:
        add('reviewed', '须满足依据截止≤复核时点≤登记时点，且为完整本地日期时间')
    for f in ('reference', 'note'):
        if not isinstance(row.get(f), str) or not row[f].strip():
            add(f, '填写复核文件编号及结论或变更原因')
    return out


def basis_rule():
    root = Path(__file__).parent
    return metrology.digest({p: (root/p).read_text() for p in ('first_review.py', 'first_piece.py', 'process_quality.py', 'metrology.py')})


def basis_hash(detail, data, cutoff):
    """Bind relevant known facts and interpretation; omit prices and future counts."""
    index = {ds: {r['id']: r for r in rows} for ds, rows in data.items()}
    facts = []
    for source in detail['sources']:
        ds, key = source['dataset'], source['key']
        row = index.get(ds, {}).get(key)
        if row and metrology.clock(row.get('registered')) and row['registered'] > cutoff:
            continue
        # Draft registers do not supersede known versions or their review basis.
        if row and ds.startswith('metrology_') and row.get('status') == '草稿':
            continue
        facts.append(dict(dataset=ds, key=key, values={k: v for k, v in row.items() if 'cents' not in k} if row else None))
    row = {k: v for k, v in detail['row'].items() if k not in ('future_checks', 'approval')}
    return metrology.digest(dict(row=row, measures=detail['measures'], executions=detail['executions'], expected=detail['expected'], facts=facts))


def analyze(data, first, cutoff):
    raw = data.get(DATASET, [])
    by_plan = defaultdict(list)
    for r in raw:
        by_plan[r.get('plan_id')].append(r)
    groups = {g['series']: g for g in metrology.resolve_versions([dict(r, series=r.get('plan_id')) for r in raw], cutoff, ('plan_id',))}
    cache = {cutoff: first}
    rule = basis_rule()
    rows = {}
    # Cache whole evaluations for shared review cutoffs; fall back to a bounded
    # plan evaluation for many distinct times instead of growing an unbounded cache.
    def historical(plan, at):
        if at not in cache and len(cache) < 16:
            cache[at] = first_piece.analyze(data, at)
        if at in cache:
            return cache[at]['details'][plan]
        local = dict(data)
        local['process_check_plans'] = [p for p in data.get('process_check_plans', []) if p['id'] == plan]
        local['process_checks'] = [c for c in data.get('process_checks', []) if c['plan_id'] == plan]
        checks = {c['id'] for c in local['process_checks']}
        local['process_readings'] = [r for r in data.get('process_readings', []) if r['check_id'] in checks]
        return first_piece.analyze(local, at)['details'][plan]
    for plan, detail in first['details'].items():
        history = sorted(by_plan.get(plan, []), key=lambda r: (r.get('registered') or '', r.get('version', 0), r['id']))
        group = groups.get(plan)
        selected = group['selected'] if group else None
        selected = {k: v for k, v in selected.items() if k != 'series'} if selected else None
        reasons = list(group['issues']) if group else []
        state = 'invalid' if reasons else 'none'
        current_hash = basis_hash(detail, data, cutoff)
        assessed_hash = None
        if selected:
            reasons += [p['message'] for p in issues(selected)]
            if selected.get('reviewer_id') not in {r['id'] for r in data.get('employees', [])}:
                reasons.append('复核人员档案缺失')
            if reasons:
                state = 'invalid'
            elif selected['status'] == '撤销':
                state = 'withdrawn'
            else:
                basis = historical(plan, selected['basis_at'])
                assessed_hash = basis_hash(basis, data, selected['basis_at'])
                if selected['check_id'] != basis['row']['latest_id']:
                    state = 'invalid'
                    reasons.append('引用检验不是此计划在依据截止时的最新非作废记录')
                elif selected['rule_hash'] != rule:
                    state = 'stale'
                    reasons.append('依据计算规则已变化')
                elif selected['basis_hash'] != assessed_hash:
                    state = 'stale'
                    reasons.append('当前事实重放与登记的依据摘要不符')
                elif current_hash != assessed_hash:
                    state = 'stale'
                    reasons.append('依据截止后已有新检验、计量登记或其他相关事实变化')
                elif selected['decision'] == '复核通过' and detail['row']['evidence_state'] != 'ready':
                    state = 'contradicted'
                    reasons.append('通过登记不能覆盖待检、超限、漏项或资料/计量疑点')
                else:
                    state = {'复核通过': 'matched', '不予通过': 'held', '待补充': 'pending'}[selected['decision']]
        rows[plan] = dict(plan_id=plan, state=state, label=STATES[state], selected=selected, reasons=list(dict.fromkeys(reasons)),
                          history=history, current_basis_hash=current_hash, replayed_basis_hash=assessed_hash, current_rule_hash=rule,
                          sources=[dict(dataset=DATASET, key=r['id']) for r in history]+[dict(dataset='employees', key=r['reviewer_id']) for r in history])
    counts = Counter(r['state'] for r in rows.values())
    return dict(rows=rows, summary={k: counts[k] for k in STATES}, labels=STATES, notice=NOTICE,
                unmatched=[dict(id=r['id'], plan_id=r.get('plan_id'), reason='引用计划不在首件队列中') for r in raw if r.get('plan_id') not in first['details']])
