import tempfile
from . import access,import_mapping
from .views import api,require,reply


@api(('POST',))
def inspect(request):
    require(access.can_import(request.user))
    file=request.FILES.get('file')
    if not file or not file.name.lower().endswith('.xlsx'):raise ValueError('请选择.xlsx工作簿')
    if file.size>50*1024*1024:raise ValueError('文件超过50MB')
    strict=request.path.endswith('/preview')
    mapping=import_mapping.parse_mapping(request.POST.get('mapping','{}')) if strict else None
    with tempfile.NamedTemporaryFile(suffix='.xlsx') as temp:
        for chunk in file.chunks():temp.write(chunk)
        temp.flush();result=import_mapping.inspect(temp.name,request.user,mapping,strict,filename=file.name)
    response=reply(result);response['Cache-Control']='no-store';return response
