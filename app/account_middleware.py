from django.contrib.auth import logout
from . import accounts,access
from .models import AccountAccessState

class AccountSessionMiddleware:
    """Invalidate old logins on the next request, without rewriting business records."""
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        user=request.user
        if user.is_authenticated:
            epoch=AccountAccessState.objects.filter(user=user).values_list('session_epoch',flat=True).first() or 0
            stamp=accounts.session_stamp(user)
            if access.role(user) is None or request.session.get(accounts.SESSION_KEY,0)!=epoch or request.session.get(accounts.STAMP_KEY,stamp)!=stamp:
                logout(request)
            elif accounts.STAMP_KEY not in request.session:
                request.session[accounts.STAMP_KEY]=stamp
                request.session[accounts.SESSION_KEY]=epoch
        result=self.get_response(request)
        if request.path.startswith('/api/'):result['Cache-Control']='no-store'
        return result
