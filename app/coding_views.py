from .views import api,reply,body,require
from . import access,coding,coding_lifecycle as life
from .models import CodingRule,CodeAllocation
from django.core.exceptions import ValidationError

@api(('GET','POST'))
def collection(request):
    if request.method=='GET':return reply([life.info(r) for r in CodingRule.objects.all().order_by('id')])
    return reply(life.create(request.user,body(request)))

@api()
def detail(request,rule_id):return reply(life.info(CodingRule.objects.get(pk=rule_id),True))

@api(('POST',))
def draft(request,rule_id):return reply(life.save_draft(request.user,rule_id,body(request)))

@api(('POST',))
def transition(request,rule_id):return reply(life.transition(request.user,rule_id,body(request)))

@api(('POST',))
def allocate(request,rule_id):
    require(access.role(request.user)=='admin');data=body(request)
    if type(data.get('preview')) is not bool:raise ValidationError('请明确选择预览或正式申请')
    if data['preview']:
        if set(data)!={'date','count','preview'}:raise ValidationError('预览只接受业务日期、数量和预览标识')
        return reply({**coding.preview(rule_id,data['date'],data['count'],request.user.username),'preview':True})
    try:return reply(coding.issue(rule_id,data,request.user.username))
    except coding.PreviewExpired as ex:return reply({'error':str(ex),'code':'coding_preview_expired','committed':False},409)

@api(('POST',))
def advance(request,rule_id):return reply(life.advance(request.user,rule_id,body(request)))

@api()
def allocations(request,rule_id):
    rule=CodingRule.objects.get(pk=rule_id);query=CodeAllocation.objects.filter(rule=rule).select_related('request').order_by('-id')
    term=request.GET.get('q','').strip()
    if len(term)>100:raise ValidationError('检索值过长')
    if term:query=query.filter(code__icontains=term)
    version=request.GET.get('version','')
    if version:
        if not version.isdigit() or len(version)>8:raise ValidationError('版本须为正整数')
        query=query.filter(rule_version=int(version))
    for key,field in [('from','business_date__gte'),('to','business_date__lte')]:
        if request.GET.get(key):query=query.filter(**{field:coding.business_date(request.GET[key])})
    if request.GET.get('from','')>request.GET.get('to','9999-12-31'):raise ValidationError('开始日期晚于结束日期')
    page=max(1,min(100000,int(request.GET.get('page',1))));total=query.count()
    rows=[{'id':a.pk,'code':a.code,'rule_version':a.rule_version,'allocated_by':a.allocated_by,'created_at':a.created_at,
           'business_date':a.business_date,'period':a.period,'sequence':a.sequence,'definition':a.definition,
           'request_id':a.request_id,'purpose':a.request.purpose if a.request else '旧版或业务流程内发号；详见审计'} for a in query[(page-1)*25:page*25]]
    return reply({'rule_id':rule.pk,'rows':rows,'total':total,'page':page,'size':25,
                  'note':'按发号业务日期筛选；旧记录无法从审计核实日期时保留未知，不冒用创建时间。发号记录不能证明该编号已经投入业务。'})
