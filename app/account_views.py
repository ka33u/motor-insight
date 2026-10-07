from django.contrib.auth.models import User
from django.db import transaction
from . import accounts
from .views import api,reply,body
from .models import AuditEvent

def response(data,status=200):
    r=reply(data,status);r['Cache-Control']='no-store';return r

@api(('GET','POST'))
def collection(request):
    accounts.require_admin(request.user)
    if request.method=='POST':return response(accounts.create(request.user,body(request)),201)
    q=request.GET.get('q','').strip();role=request.GET.get('role','');status=request.GET.get('status','all');page=max(1,int(request.GET.get('page',1)))
    if len(q)>150 or role and role not in accounts.access.ROLES or status not in ['all','active','inactive','conflict']:raise ValueError('账号筛选条件无效')
    rows=[accounts.profile(u) for u in User.objects.order_by('username')]
    selected=[r for r in rows if (not q or q.lower() in (r['username']+' '+r['display_name']).lower()) and (not role or r['role']==role or role=='admin' and r['is_superuser']) and (status=='all' or status=='active' and r['is_active'] or status=='inactive' and not r['is_active'] or status=='conflict' and len(r['assigned_roles'])>1 and not r['is_superuser'])]
    return response({'rows':selected[(page-1)*25:page*25],'total':len(selected),'page':page,'size':25,'filters':{'q':q,'role':role,'status':status},'roles':accounts.roles(),'capability_labels':accounts.CAPABILITY_LABELS,'notice':accounts.NOTICE,'actor_id':request.user.pk,'summary':{'total':len(rows),'active':sum(r['is_active'] for r in rows),'inactive':sum(not r['is_active'] for r in rows),'conflict':sum(len(r['assigned_roles'])>1 and not r['is_superuser'] for r in rows)}})

@api()
def detail(request,user_id):
    accounts.require_admin(request.user);u=User.objects.get(pk=user_id)
    return response({'user':accounts.profile(u),'permissions':accounts.permission_profile(u),'receipt':accounts.current_receipt(u),
                     'history':list(AuditEvent.objects.filter(object_type='UserAccess',object_id=str(u.pk)).order_by('-id').values('action','actor','detail','created_at')[:50]),'notice':accounts.NOTICE})

@api(('POST',))
@transaction.atomic
def preview(request,user_id):
    accounts.require_admin(request.user);return response(accounts.preview(request.user,User.objects.get(pk=user_id),body(request)))

@api(('POST',))
def update(request,user_id):return response(accounts.update(request.user,user_id,body(request)))

@api(('POST',))
def revoke(request,user_id):return response(accounts.revoke(request.user,user_id,body(request)))
