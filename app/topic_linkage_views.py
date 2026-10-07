"""A chart selection proposes a normal, inspectable topic configuration."""
from django.core.exceptions import ValidationError
from django.db import transaction
from . import topic_workspace as ws,topic_linkage as links
from .views import api,body,reply
from .import_review import ReviewConflict
from .file_sharing import fresh

@api(('POST',))
@transaction.atomic
def select(request,topic_id):
    if request.GET:raise ValidationError('点选联动不接受查询参数')
    data=body(request)
    if set(data)!={'context_token','facts_token','config','slot','side','group'}:raise ValidationError('点选须带完整专题范围、来源依据及真实分组')
    if type(data['slot']) is not int or data['side'] not in ('primary','reference') or not isinstance(data['group'],str) or not 1<=len(data['group'])<=150:raise ValidationError('点选卡片、范围或分组无效')
    result=ws.run(fresh(request.user),topic_id,{k:data[k] for k in ('context_token','config')})
    if data['facts_token']!=result['facts_token']:raise ReviewConflict('点选依据已更新，请刷新专题后重新点选')
    card=next((c for c in result['cards'] if c['slot']==data['slot']),None)
    if not card or not card.get(data['side']):raise ValidationError('所选卡片或范围未计算，不能据此联动')
    # Resolve the actual group on the specifically requested side, not the
    # client-provided field name or a display label guessed to be an identity.
    scope=result['config']['scope' if data['side']=='primary' else 'reference_scope']
    available=links.choices(fresh(request.user),card['model'],card[data['side']],scope,data['side'])
    choice=next((c for c in available if c['group']==data['group']),None)
    if choice is None:raise ValidationError('此分组没有可核对的直接身份关系；名称、日期、缺失值和个人分组不自动联动')
    conf=result['config'];selections=[s for s in conf.get('links',{}).get('selections',[]) if s['kind']!=choice['kind']]
    selections.append(dict(kind=choice['kind'],value=choice['value']))
    conf['links']=links.validate(dict(revision=links.REVISION,rules_hash=links.rules_hash(),selections=selections))
    ctx=ws.context(fresh(request.user),topic_id)
    if ctx['context_token']!=result['context_token'] or ws.digest(ws.analytics.revision())!=result['facts_token']:raise ReviewConflict('点选期间专题或事实已变化，请刷新重试')
    response=reply(dict(config=conf,selection=choice,notice=links.NOTICE));response['Cache-Control']='no-store';return response
