from . import model_changes
from .views import api,body,reply


def response(data):
    result=reply(data);result['Cache-Control']='no-store';return result


def input_data(request):
    if request.GET:raise ValueError('变更条件必须通过请求内容传递')
    return body(request)


@api(('POST',))
def preview(request,key):return response(model_changes.preview(request.user,key,input_data(request)))


@api(('POST',))
def evidence(request,key):return response(model_changes.evidence(request.user,key,input_data(request)))


@api(('POST',))
def commit(request,key):return response(model_changes.commit(request.user,key,input_data(request)))


@api()
def history(request,key):
    if set(request.GET)-{'page'} or any(len(request.GET.getlist(k))!=1 for k in request.GET):raise ValueError('历史查询参数无效')
    page=request.GET.get('page','1')
    if not page.isascii() or not page.isdecimal() or not 1<=int(page)<=1000000:raise ValueError('历史页码无效')
    return response(model_changes.history(request.user,key,int(page)))
