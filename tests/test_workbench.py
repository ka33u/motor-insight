import copy,json,re,uuid
from pathlib import Path
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError,PermissionDenied
from django.test import TestCase,Client,RequestFactory
from app import workbench as w,topic_workspace as ws,topic_pages,model_cards
from app.models import PersonalWorkbench,WorkbenchEntry,AnalysisModel,Topic,TopicView,AuditEvent,Record,CodingRule
from app.import_review import ReviewConflict

class WorkbenchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users={}
        for role in ('admin','analyst','quality','operations','finance','viewer'):
            u=User.objects.create_user(username='desk_'+role);u.groups.add(Group.objects.get_or_create(name=role)[0]);cls.users[role]=u
        cls.model=AnalysisModel.objects.create(name='分车间能耗',dataset='energy',definition=dict(dimension='workshop',metrics=[dict(agg='sum',field='kwh')],chart='bar'),owner=cls.users['admin'].username,is_public=True)
        cls.topic=Topic.objects.create(name='每日能耗核查',description='合成演练',owner=cls.users['admin'].username,is_public=True,layout=[dict(model_id=cls.model.pk,span=1)])
        cls.coding=CodingRule.objects.create(key='daily',name='日常编码',prefix='DM',date_format='%y%m%d',width=5,separator='-',reset_period='day')
    def setUp(self):self.user=self.users['viewer'];self.client.force_login(self.user)
    def add(self,kind='module',target='delivery',user=None,**fields):
        u=user or self.user;return w.change(u,{**dict(action='add',revision=w.board(u)['revision'],kind=kind,target=str(target),alias='',section=''),**fields})
    def mutate(self,action,user=None,**fields):
        u=user or self.user;return w.change(u,dict(action=action,revision=w.board(u)['revision'],**fields))
    def view(self,user=None):
        u=user or self.user;ctx=ws.context(u,self.topic.pk);return ws.save_view(u,self.topic.pk,dict(name='我的夜班视角',config=dict(scope={},reference_scope=None,primary_label='当前',reference_label='对照'),context_token=ctx['context_token']))
    def page(self,user=None):
        u=user or self.user;definition=dict(topic_id=self.topic.pk,code='PAGE.DESK.001',title='我的早会页面',question='核对当前能耗',cadence='每日',sections=[dict(id='MAIN',title='主结果',role='result',note='',cards=[dict(slot=0,span=2,title='',note='')])],navigation=[])
        p=topic_pages.preview(u,definition);return topic_pages.save(u,dict(request_id=str(uuid.uuid4()),definition=definition,receipt=p['receipt'],reason='合成演练核对页面'))
    def card(self,user=None):
        u=user or self.user;p=model_cards.preview(u,self.model.pk);c,_,_=model_cards.save(u,dict(request_id=str(uuid.uuid4()),code='CARD.DESK.001',name='能耗口径卡',question='检查能耗',reader='车间',object_grain='能源记录',time_scope='原模型时间',limitations='合成资料',review_on=None,model_id=self.model.pk,receipt=p['receipt']));return c
    def test_empty_reads_never_create_preferences_or_business_data(self):
        self.assertEqual(w.board(self.user)['revision'],0);self.assertEqual(w.start(self.user)['route'],'overview');w.catalog(self.user,dict(kind='module',q='',page=1));self.assertFalse(PersonalWorkbench.objects.exists());self.assertFalse(AuditEvent.objects.exists());self.assertFalse(Record.objects.exists())
    def test_seven_target_kinds_open_real_internal_routes(self):
        view=self.view();page=self.page();card=self.card()
        targets=[('module','delivery','delivery'),('model',self.model.pk,'analysis'),('topic',self.topic.pk,'topics'),('view',view['id'],'topics'),('page',page['id'],'topics'),('card',card.pk,'model-cards'),('coding',self.coding.pk,'coding')]
        for kind,target,route in targets:
            d=self.add(kind,target);row=d['rows'][-1];opened=w.open_entry(self.user,dict(id=row['id'],revision=d['revision']));self.assertEqual(opened['route'],route);self.assertEqual(opened['state'],'ready')
        self.assertEqual(WorkbenchEntry.objects.count(),7);self.assertFalse(Record.objects.exists())
    def test_six_roles_have_independent_favorites(self):
        for u in self.users.values():d=self.add(user=u);self.assertEqual(len(d['rows']),1)
        self.assertEqual(PersonalWorkbench.objects.count(),6);self.assertEqual(WorkbenchEntry.objects.count(),6)
        foreign=w.board(self.users['admin'])['rows'][0]['id']
        with self.assertRaises(WorkbenchEntry.DoesNotExist):w.open_entry(self.user,dict(id=foreign,revision=1))
        with self.assertRaises(WorkbenchEntry.DoesNotExist):self.mutate('remove',id=foreign)
    def test_stale_revision_duplicate_and_identity_not_editable(self):
        d=self.add();row=d['rows'][0]
        with self.assertRaises(ReviewConflict):self.add()
        with self.assertRaises(ReviewConflict):w.change(self.user,dict(action='remove',id=row['id'],revision=0))
        with self.assertRaises(ValidationError):self.mutate('edit',id=row['id'],alias='x',section='',target='quality')
        self.assertEqual(WorkbenchEntry.objects.count(),1)
    def test_rename_group_and_complete_order_are_persisted(self):
        self.add();d=self.add(target='quality');a,b=d['rows'];self.mutate('edit',id=a['id'],alias='早会交付',section='早会');d=self.mutate('order',ids=[b['id'],a['id']]);self.assertEqual([r['id'] for r in d['rows']],[b['id'],a['id']]);self.assertEqual(d['rows'][1]['alias'],'早会交付');self.assertEqual(d['rows'][1]['section'],'早会')
        for ids in ([],[a['id'],a['id']],[a['id'],str(uuid.uuid4())]):
            with self.assertRaises(ValidationError):self.mutate('order',ids=ids)
    def test_removal_compacts_order_and_clears_home(self):
        a=self.add()['rows'][0];self.add(target='quality');self.mutate('home',id=a['id']);d=self.mutate('remove',id=a['id']);self.assertEqual(d['rows'][0]['position'],0);self.assertIsNone(d['home_entry']);self.assertEqual(w.start(self.user)['route'],'overview')
    def test_login_can_start_workbench_favorite_or_overview(self):
        self.mutate('home',id='workbench');self.assertEqual(w.start(self.user)['route'],'workbench');d=self.add();self.mutate('home',id=d['rows'][0]['id']);self.assertEqual(w.start(self.user)['route'],'delivery');self.mutate('home',id=None);self.assertFalse(w.start(self.user)['configured'])
    def test_role_revocation_masks_target_and_falls_back(self):
        u=self.users['finance'];d=self.add('module','receivables',u);self.mutate('home',u,id=d['rows'][0]['id']);u.groups.clear();u.groups.add(Group.objects.get(name='viewer'))
        row=w.board(u)['rows'][0];self.assertEqual(row['label'],'目标当前不可用');self.assertIsNone(row['route']);self.assertEqual(w.start(u)['route'],'workbench')
        with self.assertRaises(ReviewConflict):w.open_entry(u,dict(id=row['id'],revision=d['revision']+1))
    def test_private_targets_absent_from_directory_without_count_leak(self):
        other=AnalysisModel.objects.create(name='不应泄露',dataset='energy',definition=self.model.definition,owner=self.users['analyst'].username,is_public=False)
        d=w.catalog(self.user,dict(kind='model',q='',page=1));self.assertEqual(d['total'],1);self.assertNotIn('不应泄露',json.dumps(d,ensure_ascii=False))
        with self.assertRaises(AnalysisModel.DoesNotExist):self.add('model',other.pk)
    def test_private_view_page_card_are_not_visible_to_other_accounts_even_admin(self):
        v=self.view();p=self.page();c=self.card()
        for kind,target in [('view',v['id']),('page',p['id']),('card',c.pk)]:
            d=w.catalog(self.users['admin'],dict(kind=kind,q='',page=1));self.assertEqual(d['total'],0)
            self.assertEqual(w.safe_target(self.users['admin'],kind,str(target))['state'],'unavailable')
    def test_saved_view_stale_is_review_and_cannot_be_new_home(self):
        v=self.view();d=self.add('view',v['id']);self.model.version+=1;self.model.save();row=w.board(self.user)['rows'][0];self.assertEqual(row['state'],'review')
        with self.assertRaises(ValidationError):self.mutate('home',id=row['id'])
        self.assertEqual(w.open_entry(self.user,dict(id=row['id'],revision=d['revision']))['params']['view'],str(v['id']))
    def test_page_drift_routes_to_definition_and_archive_masks_title(self):
        p=self.page();self.add('page',p['id']);self.model.version+=1;self.model.save();row=w.board(self.user)['rows'][0];self.assertEqual((row['state'],row['route']),('review','topic-pages'))
        from app.models import TopicPage
        TopicPage.objects.filter(pk=p['id']).update(archived=True);row=w.board(self.user)['rows'][0];self.assertEqual(row['state'],'unavailable');self.assertEqual(row['label'],'目标当前不可用')
    def test_model_latest_definition_and_private_change_rechecked(self):
        d=self.add('model',self.model.pk);self.model.name='新的当前名称';self.model.version+=1;self.model.save();row=w.board(self.user)['rows'][0];self.assertEqual((row['label'],row['version']),('新的当前名称',2))
        self.model.is_public=False;self.model.save();self.assertEqual(w.board(self.user)['rows'][0]['state'],'unavailable')
    def test_unavailable_model_does_not_expose_financial_names(self):
        d=self.add('model',self.model.pk);self.model.dataset='costs';self.model.definition=dict(metrics=[dict(agg='sum',field='amount_cents')]);self.model.name='保密利润';self.model.save();self.assertNotIn('保密利润',json.dumps(w.board(self.user),ensure_ascii=False));self.assertEqual(w.catalog(self.user,dict(kind='model',q='',page=1))['total'],0)
    def test_module_permissions_match_sidebar_and_all_destinations_are_internal(self):
        for role,u in self.users.items():
            d=w.catalog(u,dict(kind='module',q='',page=1));rows=d['rows']
            for p in range(2,(d['total']+24)//25+1):rows+=w.catalog(u,dict(kind='module',q='',page=p))['rows']
            keys={r['target'] for r in rows};self.assertEqual('accounts' in keys,role=='admin');self.assertEqual('receivables' in keys,role in ('admin','analyst','finance'));self.assertEqual('crew-schedule' in keys,role in ('admin','analyst','operations'));self.assertEqual('device-files' in keys,role in ('admin','quality'));self.assertTrue(all(re.fullmatch('[a-z-]+',r['route']) for r in rows))
        source=(Path(__file__).resolve().parents[1]/'static/app.js').read_text();part=source[source.index('const nav='):source.index('function shell()')];names={k:v for k,icon,v in re.findall(r"\['([^']+)','([^']*)','([^']+)'\]",part)};self.assertEqual(names,w.ROUTES)
    def test_invalid_target_and_control_characters_fail_without_changes(self):
        for kind,value in [('module','javascript:alert(1)'),('model','01'),('model','-1'),('model','1?x=1'),('page','../x'),('view',True)]:
            with self.assertRaises(ValidationError):w.change(self.user,dict(action='add',revision=0,kind=kind,target=value,alias='',section=''))
        with self.assertRaises(ValidationError):self.add(alias='a\x00b')
        self.assertFalse(PersonalWorkbench.objects.exists());self.assertFalse(AuditEvent.objects.exists())
    def test_max_100_and_catalog_paging_search(self):
        for i in range(31):AnalysisModel.objects.create(name=f'观察模型{i:02d}',dataset='energy',definition=self.model.definition,owner=self.user.username)
        a=w.catalog(self.user,dict(kind='model',q='观察模型',page=1));b=w.catalog(self.user,dict(kind='model',q='观察模型',page=2));self.assertEqual((a['total'],len(a['rows']),len(b['rows'])),(31,25,6));self.assertFalse(set(r['target'] for r in a['rows'])&set(r['target'] for r in b['rows']))
        self.add()
        with patch('app.workbench.LIMIT',1),self.assertRaises(ValidationError):self.add(target='quality')
    def test_fresh_disabled_and_conflicting_account_rejected(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):w.board(self.user)
        User.objects.filter(pk=self.user.pk).update(is_active=True);self.user.groups.add(Group.objects.get(name='finance'))
        with self.assertRaises(PermissionDenied):w.start(self.user)
    def test_audit_failure_rolls_back_and_existing_facts_models_topics_unchanged(self):
        before=(list(Record.objects.values()),list(AnalysisModel.objects.values()),list(Topic.objects.values()))
        with patch('app.workbench.AuditEvent.objects.create',side_effect=ValueError('audit failed')),self.assertRaises(ValueError):self.add()
        self.assertFalse(PersonalWorkbench.objects.exists());self.add();self.assertEqual(before,(list(Record.objects.values()),list(AnalysisModel.objects.values()),list(Topic.objects.values())))
        event=AuditEvent.objects.get();self.assertFalse(event.detail['business_facts_changed']);self.assertNotIn('definition',json.dumps(event.detail))
    def test_http_methods_csrf_no_cache_and_anonymous(self):
        self.assertEqual(self.client.get('/api/workbench')['Cache-Control'],'no-store');self.assertEqual(self.client.get('/api/workbench/catalog').status_code,405);self.assertEqual(self.client.get('/api/workbench?q=x').status_code,400)
        c=Client(enforce_csrf_checks=True);c.force_login(self.user);self.assertEqual(c.post('/api/workbench','{}',content_type='application/json').status_code,403)
        self.client.logout();self.assertEqual(self.client.get('/api/workbench').status_code,401)
    def test_strict_fields_revision_and_foreign_order(self):
        for data in (dict(action='home',revision=True,id=None),dict(action='home',revision=0,id=None,extra=1),dict(action='bad',revision=0)):
            with self.assertRaises((ValidationError,ReviewConflict)):w.change(self.user,data)
        for p in (0,True,'1',1001):
            with self.assertRaises(ValidationError):w.catalog(self.user,dict(kind='model',q='',page=p))
    def test_read_open_are_not_usage_telemetry(self):
        d=self.add();before=list(AuditEvent.objects.values());w.board(self.user);w.open_entry(self.user,dict(id=d['rows'][0]['id'],revision=d['revision']));w.start(self.user);self.assertEqual(list(AuditEvent.objects.values()),before)
