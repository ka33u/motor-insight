from . import topic_journey as journey
from .views import api, body, reply


def response(data):
    result = reply(data)
    result['Cache-Control'] = 'no-store'
    return result


def checked_body(request):
    if request.GET:
        raise ValueError('探索条件仅通过请求内容传递')
    return body(request)


@api(('POST',))
def preview(request, key):
    return response(journey.preview(request.user, key, checked_body(request)))


@api(('POST',))
def open_journey(request, key):
    return response(journey.open_journey(request.user, key, checked_body(request)))


@api(('POST',))
def resolve(request, key):
    return response(journey.resolve(request.user, key, checked_body(request)))
