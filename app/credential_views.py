import logging
from django.contrib.auth import logout
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import IntegrityError, OperationalError
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from . import credentials
from .views import api, body, reply
from .import_review import ReviewConflict


def response(value, status=200):
    result = reply(value, status)
    result['Cache-Control'] = 'no-store'
    return result


def failure(error):
    # Preserve the API's normal controlled errors. Unexpected credential
    # failures must never produce a DEBUG traceback with submitted secrets.
    if isinstance(error, (ObjectDoesNotExist, PermissionDenied, ValidationError,
                          ReviewConflict, IntegrityError)):
        raise error
    if isinstance(error, (ValueError, TypeError)):
        return response({'error': '口令维护参数无法解析，请重新核对输入'}, 400)
    if isinstance(error, OperationalError) and 'locked' in str(error).lower():
        return response({'error': '当前有其他写入操作，请重新读取账号后再核对'}, 409)
    logging.getLogger(__name__).error('Credential mutation failed: %s', type(error).__name__)
    return response({'error': '口令维护未完成，请重新读取账号状态后再核对；业务数据未修改'}, 500)


@api()
def context(request):
    return response(credentials.context(request.user))


@api(('POST',))
@sensitive_post_parameters()
@sensitive_variables('data', 'value')
def change(request):
    try:
        value = credentials.change(request.user, body(request))
    except Exception as error:
        return failure(error)
    logout(request)
    return response(value)


@api(('POST',))
def reset_preview(request, user_id):
    return response(credentials.reset_preview(request.user, user_id, body(request)))


@api(('POST',))
@sensitive_post_parameters()
@sensitive_variables('data', 'value')
def reset(request, user_id):
    try:
        return response(credentials.reset(request.user, user_id, body(request)))
    except Exception as error:
        return failure(error)
