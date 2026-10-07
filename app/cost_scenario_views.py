import csv,io,json,re
from urllib.parse import quote
from django.http import HttpResponse
from .views import api,reply,body
from . import cost_scenarios as scenarios

@api()
def options(request):return reply(scenarios.options(request.user))
@api(('POST',))
def baseline(request):return reply(scenarios.public_baseline(scenarios.baseline(request.user,body(request))))
@api(('POST',))
def evaluate(request):return reply(scenarios.public_run(scenarios.evaluate(request.user,body(request))))
@api(('POST',))
def save(request):return reply(scenarios.info(scenarios.save(request.user,body(request))))
@api()
def detail(request,scenario_id):
    r=scenarios.get(request.user,scenario_id);return reply({**scenarios.info(r),'run':scenarios.public_run(r.payload)})
@api(('POST',))
def evidence(request,scenario_id=None):return reply(scenarios.evidence(request.user,body(request),scenario_id))
@api()
def export(request,scenario_id):
    r=scenarios.get(request.user,scenario_id)
    if request.GET.get('format')=='json':
        response=HttpResponse(json.dumps({**scenarios.info(r),'payload':r.payload},ensure_ascii=False,default=str,indent=2),content_type='application/json; charset=utf-8');extension='json'
    else:
        stream=io.StringIO();w=csv.writer(stream)
        def safe(v):return "'"+v if isinstance(v,str) and re.match(r'^[\s]*[=+@\-\t\r]',v) else '' if v is None else v
        for row in scenarios.csv_rows(r):w.writerow([safe(v) for v in row])
        response=HttpResponse('\ufeff'+stream.getvalue(),content_type='text/csv; charset=utf-8');extension='csv'
    response['Content-Disposition']="attachment; filename*=UTF-8''"+quote(f'成本情景-{r.pk}.{extension}')
    response['Cache-Control']='no-store';return response
