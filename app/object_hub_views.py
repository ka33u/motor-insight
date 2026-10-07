from . import object_hub
from .views import api, body, reply


def respond(data):
    response = reply(data)
    response['Cache-Control'] = 'no-store'
    return response


def no_query(request):
    if request.GET:
        raise ValueError('对象查找条件通过请求内容传递，不能附加URL参数')


@api(('POST',))
def search(request):
    no_query(request)
    return respond(object_hub.search(request.user, body(request)))


@api()
def detail(request, record_id):
    no_query(request)
    return respond(object_hub.detail(request.user, record_id))


@api(('POST',))
def related(request, record_id):
    no_query(request)
    return respond(object_hub.related(request.user, record_id, body(request)))
