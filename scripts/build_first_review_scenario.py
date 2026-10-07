"""Generate synthetic declarations; business data still enters through Excel."""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from app import first_piece_data, first_piece, first_review, analytics
from app.models import Record
from app.schema import SCHEMAS


def main():
    original = first_piece_data.load()
    wanted = defaultdict(list)
    for source in original['sources']:
        wanted[source['dataset']].append(source['key'])
    data = {}
    for ds, keys in wanted.items():
        data[ds] = list(Record.objects.filter(dataset=ds, business_key__in=keys).order_by('business_key').values_list('values', flat=True))
    assert not data.get(first_review.DATASET), 'Generate once before importing this input.'
    at = '2026-10-01T17:00:00'
    basis = first_piece.analyze(data, at)
    rows = []
    for i, (key, detail) in enumerate(basis['details'].items(), 1):
        state = detail['row']['evidence_state']
        decision = '复核通过' if state == 'ready' else '不予通过' if state == 'out' else '待补充'
        if state == 'ready' and i % 11 == 0:
            decision = '不予通过'
        rows.append(dict(id=f'SJ-FH-261001-{i:04}-V01', plan_id=key, version=1, previous_id=None, status='已登记', basis_at=at,
                         check_id=detail['row']['latest_id'], basis_hash=first_review.basis_hash(detail, data, at), rule_hash=first_review.basis_rule(),
                         reviewed='2026-10-01T17:05:00', registered='2026-10-01T17:10:00', decision=decision, reviewer_id='E00007',
                         reference=f'SIM-SJ-FH-261001-{i:04}', note='合成演练：按登记截止核对已有首件与计量资料。结论不代表真实人员签字或生产许可。'))
    ready = [r for r in rows if basis['details'][r['plan_id']]['row']['evidence_state'] == 'ready']
    def version(row, **delta):
        new = dict(row, id=row['id'].replace('-V01', '-V02'), version=2, previous_id=row['id'], registered='2026-10-01T17:30:00')
        new.update(delta)
        new['id'] = row['id'].rsplit('-V', 1)[0]+f"-V{new['version']:02}"
        rows.append(new)
    version(ready[0], status='撤销', note='合成案例：撤销原复核，不得回退使用旧通过。')
    version(ready[1], decision='待补充', note='合成案例：最新登记要求补充资料，旧通过不再生效。')
    ready[2].update(basis_hash='f'*64, note='合成案例：登记依据摘要与重放内容不符。')
    ready[3].update(rule_hash='f'*64, note='合成案例：复核采用的规则摘要已不一致。')
    ready[4].update(check_id=ready[5]['check_id'], note='合成案例：引用其他首件计划的检验记录。')
    version(ready[5], version=3, note='合成案例：版本从1跳到3，版本链缺项。')
    version(ready[6], status='草稿', decision='待补充', note='合成案例：新草稿不得替代已登记版本。')
    ready[7].update(status='草稿', note='合成案例：仅有草稿，尚无生效复核。')
    ready[8].update(registered='2026-10-02T08:00:00', note='合成案例：未来才登记，当前尚不可用。')
    detail = basis['details'][ready[9]['plan_id']]
    clock = min(e['row']['checked'] for e in detail['executions'])
    old_at = (datetime.fromisoformat(clock)-timedelta(minutes=1)).isoformat(timespec='seconds')
    old = first_piece.analyze(data, old_at)['details'][ready[9]['plan_id']]
    ready[9].update(basis_at=old_at, check_id=old['row']['latest_id'], basis_hash=first_review.basis_hash(old, data, old_at),
                    decision='待补充', note='合成案例：按较早资料登记待补，之后已形成新实测，需要重核。')
    rows.append(dict(ready[11], id=ready[11]['id']+'-DUP', note='合成案例：同计划存在两个已登记首版，不能任选一个。'))
    for state in ('out', 'metrology'):
        row = next(r for r in rows if basis['details'][r['plan_id']]['row']['evidence_state'] == state)
        row.update(decision='复核通过', note='合成案例：台账写通过但证据仍有疑点，应识别结论矛盾。')
    assert len(rows) == 293 and all(not first_review.issues(r) for r in rows)
    data[first_review.DATASET] = rows
    result = first_review.analyze(data, original['result'], analytics.AS_OF)
    document = dict(tables={first_review.DATASET: rows}, schemas={first_review.DATASET: SCHEMAS[first_review.DATASET]}, summary=result['summary'],
                    expected={k: v['state'] for k, v in result['rows'].items()})
    (ROOT/'data/first_review_scenario.json').write_text(json.dumps(document, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(rows=len(rows), summary=result['summary']), ensure_ascii=False))


if __name__ == '__main__':
    main()
