from django.db import transaction
from .views import api,reply,body
from . import workbench

def clean(request):
    if request.GET:raise ValueError('工作台条件须放在请求正文')

def response(value):
    r=reply(value);r['Cache-Control']='no-store';return r

@api(('GET','POST'))
@transaction.atomic
def collection(request):
    clean(request)
    return response(workbench.board(request.user) if request.method=='GET' else workbench.change(request.user,body(request)))

@api(('POST',))
@transaction.atomic
def catalog(request):
    clean(request);return response(workbench.catalog(request.user,body(request)))

@api(('POST',))
@transaction.atomic
def open_entry(request):
    clean(request);return response(workbench.open_entry(request.user,body(request)))

@api()
@transaction.atomic
def start(request):
    clean(request);return response(workbench.start(request.user))
