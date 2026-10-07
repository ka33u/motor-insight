"""Build a catalog-backed design proposal. No queries, writes or publication."""
import json
import re

FIELDS={'model','need','metric','format','code','question','owner','scope'}


def parse_input(raw):
    if not isinstance(raw,str) or len(raw)>50000:
        raise ValueError('设计输入不存在或过长')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('设计输入含重复字段')
            result[key]=value
        return result
    value=json.loads(raw,object_pairs_hook=pairs)
    if not isinstance(value,dict) or set(value)!=FIELDS:
        raise ValueError('设计输入字段不完整或含未知字段')
    return value


def build_draft(d,value):
    if set(value)!=FIELDS or any(not isinstance(x,str) for x in value.values()):
        raise ValueError('设计输入必须为完整的文本字段')
    value={k:v.strip() for k,v in value.items()}
    if not re.fullmatch(r'[A-Z][A-Z0-9._-]{2,79}',value['code']):
        raise ValueError('分析编码不可用')
    for field,limit in [('question',500),('owner',200),('scope',2000)]:
        if not value[field] or len(value[field])>limit:raise ValueError('决策问题、责任或时间范围未填写或过长')
    f=d['framework']
    model=next((m for m in f['model_library'] if m['id']==value['model']),None)
    need=next((n for dom in d['domains'] for n in dom['items'] if n['id']==value['need']),None)
    fmt=next((p for p in f['presentation_choices'] if p['id']==value['format']),None)
    metric=next((m for m in d['metrics'] if m['id']==value['metric']),None)
    if not model or not need or not fmt or (value['metric'] and not metric):raise ValueError('所选需求、模型、指标或呈现方式不在当前目录中')
    contract=next(c for c in f['domain_data_contracts'] if c['code']==need['id'].split('-')[0])
    return dict(schema='motor.bi.design-draft.v1',catalog_version=d['version'],state='设计草稿，待业务与数据评审',
        code=value['code'],version=1,question=value['question'],owner=value['owner'],
        requirement={k:need[k] for k in ['id','name','definition','priority','implementation','gap'] if k!='name'}|{'name':need['need']},
        model={k:model[k] for k in ['id','name','grain','collection_gate','guardrail']},
        metric_candidate=({k:metric[k] for k in ['id','name','formula','grain','clock','source','pitfalls']} if metric else None),
        scope=dict(user_proposal=value['scope'],domain_clock=contract['clock'],dimensions=need['dimensions'],comparison='比较基线、同配置条件和目标依据须单独审定'),
        presentation=dict(id=fmt['id'],name=fmt['name'],reader=fmt['reader'],density=fmt['density'],cards=fmt['cards'],visual=model['visual'],detail=fmt['detail'],drill=model['drill'],mobile=fmt['mobile']),
        action=dict(next_step=need['action'],boundary=fmt['avoid'],acceptance=need['acceptance']),
        data_contract=contract,pending_confirmations=f['studio_pending']+(['所选指标与模型/需求的实际粒度和维度兼容性'] if metric else ['主指标及可计算定义']),notice=f['studio_notice'])
