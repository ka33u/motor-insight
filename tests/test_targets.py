import copy,json,csv,io
from django.test import SimpleTestCase,Client
from django.contrib.auth.models import User,Group
from app.models import AnalysisModel,Record,IssueDisposition
from app import targets as k,metric_registry,access,analytics
from tests.test_platform import PlatformCase

class ComparisonTests(SimpleTestCase):
    def test_higher_lower_and_range(self):
        self.assertEqual(k.comparison(9,'gte',10,None,1)['candidate_state'],'watch')
        self.assertEqual(k.comparison(10,'gte',10,None,1)['candidate_state'],'met')
        self.assertEqual(k.comparison(12,'lte',None,10,1)['candidate_state'],'missed')
        self.assertEqual(k.comparison(11,'lte',None,10,1)['candidate_state'],'watch')
        for v in [5,7,10]:self.assertEqual(k.comparison(v,'between',5,10,1)['candidate_state'],'met')
        self.assertEqual(k.comparison(4,'between',5,10,1)['delta'],-1)
    def test_zero_and_negative_thresholds_no_division_or_reversed_score(self):
        self.assertIsNone(k.comparison(0,'gte',0,None,0)['attainment']);self.assertEqual(k.comparison(0,'lte',None,0,0)['candidate_state'],'met')
        self.assertEqual(k.comparison(-5,'lte',None,-4,0)['candidate_state'],'met');self.assertIsNone(k.comparison(-3,'gte',-4,None,0)['attainment'])
    def test_invalid_and_nonfinite_rules(self):
        for args in [(True,'gte',1,None,0),(float('nan'),'gte',1,None,0),(1,'between',2,1,0),(1,'gte',1,2,0),(1,'lte',1,2,0),(1,'gte',1,None,-1),(1,'sql',1,None,0)]:
            with self.assertRaises(ValueError):k.comparison(*args)
    def test_small_decimal_threshold(self):self.assertEqual(k.comparison(0.3,'gte',0.3,None,0)['gap'],0)

class TargetFixture(PlatformCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.admin)
        self.record('units',dict(id='U1',assembly_at='2026-09-20T08:00:00',product_id='P',work_order_id='W'))
        self.record('units',dict(id='U2',assembly_at='2026-09-20T09:00:00',product_id='P',work_order_id='W'))
        self.model=AnalysisModel.objects.create(name='测试装配数量',dataset='units',owner='admin',is_public=True,definition={'dimension':'assembly_at','grain':'day','metrics':[{'agg':'count','field':None}],'filters':[],'chart':'bar','sort':'dimension'})
        self.t=dict(id='MB-1-V01',series='MB-1',version=1,supersedes_id=None,name='模拟装配目标',department='生产',owner='模拟生产岗位',model_id=self.model.pk,model_version=self.model.version,model_signature=k.model_signature(self.model),calculation_hash=metric_registry.calculation_hash('units'),measure='m0',unit='台',period_start='2026-09-20',period_end='2026-09-20',family=None,customer_id=None,direction='gte',lower=3,upper=None,warning_margin=1,minimum_samples=1,approved='2026-09-19T08:00:00',status='已确认',basis='仅模拟假设',reason='首版')
        sig=k.evaluation(self.admin,self.t,self.model)['data_signature']
        self.c=dict(id='C1',target_id=self.t['id'],through='2026-09-20T23:59:59',confirmed='2026-09-21T08:00:00',data_signature=sig,status='完整',owner='模拟数据岗位',note='已核对模拟资料',voided=False)
        self.tables={'kpi_targets':[self.t],'kpi_target_checks':[self.c]}
    def target_row(self):return k.Targets(self.admin,self.tables).detail(self.t['id'])
    def save_targets(self):
        for ds,rows in self.tables.items():
            for r in rows:self.record(ds,r)
class TargetTests(TargetFixture):
    def test_whole_scope_and_eligible_watch(self):
        r=self.target_row();self.assertEqual((r['actual'],r['delta'],r['matched'],r['state']),(2,-1,2,'watch'));self.assertAlmostEqual(r['attainment'],2/3*100)
    def test_empty_is_unknown_not_zero(self):
        self.t.update(period_start='2026-08-01',period_end='2026-08-02');r=self.target_row();self.assertIsNone(r['actual']);self.assertEqual(r['state'],'no_sample')
    def test_source_change_invalidates_confirmation_even_same_count(self):
        before=self.target_row()['data_signature'];record=Record.objects.get(dataset='units',business_key='U1');v=copy.deepcopy(record.values);v['assembly_at']='2026-09-20T10:00:00';record.values=v;record.save();r=self.target_row();self.assertEqual(r['actual'],2);self.assertNotEqual(r['data_signature'],before);self.assertEqual(r['state'],'unconfirmed')
    def test_missing_pending_void_future_and_bad_confirmation(self):
        original=copy.deepcopy(self.c)
        for changed in [{'status':'待补'},{'voided':True},{'confirmed':'2026-10-02T08:00:00'},{'through':'2026-09-20T12:00:00'},{'confirmed':'bad'},{'owner':''},{'confirmed':'2026-09-18T08:00:00'}]:
            self.c.clear();self.c.update({**original,**changed});self.assertEqual(self.target_row()['state'],'unconfirmed')
        self.tables['kpi_target_checks']=[];self.assertEqual(self.target_row()['state'],'unconfirmed')
    def test_latest_confirmation_can_retract_completeness(self):
        self.tables['kpi_target_checks'].append({**self.c,'id':'C2','confirmed':'2026-09-22T08:00:00','status':'待补'});self.assertEqual(self.target_row()['state'],'unconfirmed')
    def test_tied_confirmation_never_arbitrarily_chosen(self):
        self.tables['kpi_target_checks'].append({**self.c,'id':'C2'});self.assertEqual(self.target_row()['state'],'unconfirmed')
    def test_model_version_definition_calculation_or_unit_drift_stops(self):
        original=copy.deepcopy(self.t)
        for changed in [{'model_version':99},{'model_signature':'0'*64},{'calculation_hash':'0'*64},{'unit':'元'},{'model_id':999},{'measure':'m9'}]:
            self.t.clear();self.t.update({**original,**changed});r=self.target_row();self.assertEqual(r['state'],'blocked');self.assertIsNone(r['actual'])
    def test_minimum_sample_guard(self):
        self.t['minimum_samples']=3;r=self.target_row();self.assertEqual(r['state'],'no_sample');self.assertEqual(r['actual'],2)
    def test_current_and_future_periods_have_no_final_lamp(self):
        self.t['period_end']='2026-10-04';r=self.target_row();self.assertEqual(r['state'],'in_progress');self.assertIsNone(r['candidate_state'])
        self.t.update(period_start='2026-10-05',period_end='2026-10-10');r=self.target_row();self.assertEqual(r['state'],'future');self.assertIsNone(r['actual'])
    def test_today_is_not_closed_before_midnight(self):
        self.t['period_end']='2026-10-01';self.assertEqual(self.target_row()['state'],'in_progress')
    def test_future_intraday_raw_record_excluded(self):
        self.t.update(period_start='2026-10-01',period_end='2026-10-01');self.record('units',dict(id='F',assembly_at='2026-10-01T20:00:00'));self.record('units',dict(id='N',assembly_at='2026-10-01T12:00:00'));self.assertEqual(self.target_row()['actual'],1)
    def test_target_version_keeps_previous_and_marks_retroactive(self):
        newer={**self.t,'id':'MB-1-V02','version':2,'supersedes_id':self.t['id'],'approved':'2026-09-22T08:00:00','lower':2}
        self.tables['kpi_targets'].append(newer);self.tables['kpi_target_checks'].append({**self.c,'id':'C2','target_id':newer['id'],'confirmed':'2026-09-23T08:00:00'})
        d=k.Targets(self.admin,self.tables);self.assertEqual(d.detail(self.t['id'])['state'],'history');self.assertEqual(d.detail(newer['id'])['state'],'met');self.assertTrue(d.detail(newer['id'])['retroactive']);self.assertEqual(d.detail(self.t['id'])['lower'],3)
    def test_future_target_revision_does_not_replace_current(self):
        self.tables['kpi_targets'].append({**self.t,'id':'V2','version':2,'supersedes_id':self.t['id'],'approved':'2026-10-02T08:00:00'});self.assertEqual(self.target_row()['state'],'watch')
    def test_bad_chain_duplicates_or_scope_change_block_series(self):
        for changes in [{'version':1},{'version':2,'supersedes_id':None},{'version':2,'supersedes_id':self.t['id'],'period_end':'2026-09-21'}]:
            self.tables['kpi_targets']=[self.t,{**self.t,'id':'V2',**changes}];self.assertEqual(self.target_row()['state'],'blocked')
    def test_user_access_and_raw_target_dataset_restrictions(self):
        self.assertFalse(access.allowed(self.quality,'kpi_targets'));self.assertFalse(access.allowed(self.quality,'kpi_target_checks'))
        with self.assertRaises(PermissionDenied):k.Targets(self.quality,self.tables)
    def test_private_model_not_exposed_to_other_analyst(self):
        analyst=User.objects.create_user('analyst');analyst.groups.add(Group.objects.create(name='analyst'));self.model.is_public=False;self.model.save();r=k.Targets(analyst,self.tables).detail(self.t['id']);self.assertEqual(r['state'],'blocked');self.assertIsNone(r['actual']);self.assertIsNone(r['model_name'])
    def test_no_period_contract_is_not_faked_by_latest_event(self):
        self.model.dataset='products';self.model.definition.update(dimension='family',grain='value');self.model.save();self.t.update(model_signature=k.model_signature(self.model),calculation_hash=metric_registry.calculation_hash('products'));self.assertEqual(self.target_row()['state'],'blocked')
    def test_unit_conversion_and_missing_numeric_field_guard(self):
        self.model.dataset='costs';self.model.definition.update(dimension='category',grain='value',metrics=[{'agg':'sum','field':'amount_cents'}]);self.model.save();self.record('costs',dict(id='C',occurred='2026-09-20',category='材料',amount_cents=12345));self.t.update(unit='元',model_signature=k.model_signature(self.model),calculation_hash=metric_registry.calculation_hash('costs'));r=self.target_row();self.assertEqual(r['actual'],123.45);self.assertEqual(r['unit_factor'],'0.01')
        self.record('costs',dict(id='NULL',occurred='2026-09-20',category='材料',amount_cents=None));e=k.evaluation(self.admin,self.t,self.model);self.c['data_signature']=e['data_signature'];r=self.target_row();self.assertEqual((r['valid_rows'],r['missing_rows'],r['state']),(1,1,'unconfirmed'))
    def test_percentage_difference_is_points(self):
        self.record('costs',dict(id='C',occurred='2026-09-20',category='材料',amount_cents=100))
        self.model.dataset='costs';self.model.definition.update(dimension='category',grain='value',metrics=[{'agg':'ratio','field':'amount_cents','denominator':'amount_cents'}]);self.model.save();self.t.update(unit='%',lower=94,model_signature=k.model_signature(self.model),calculation_hash=metric_registry.calculation_hash('costs'));r=self.target_row();self.assertEqual((r['actual'],r['delta'],r['delta_unit']),(100,6,'百分点'))
    def test_filters_history_department_and_empty(self):
        d=k.Targets(self.admin,self.tables);self.assertEqual(len(d.selected(k.params({'q':'模拟装配'}))),1);self.assertEqual(d.selected(k.params({'department':'OTHER'})),[]);self.assertEqual(k.summary([])['eligible'],0)
    def test_board_export_pagination_and_stale_receipt(self):
        self.save_targets();d=self.client.get('/api/targets').json();self.assertEqual(d['summary']['watch'],1);r=self.client.get('/api/targets/export',{'receipt':d['receipt']});self.assertEqual(r.status_code,200);rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows),6);self.assertEqual(rows[5][0],self.t['id']);self.assertEqual(self.client.get('/api/targets/export?receipt=old').status_code,409)
    def test_evidence_preserves_scope_and_rejects_wrong_object(self):
        self.save_targets();r=self.client.get('/api/targets/'+self.t['id']).json();receipt=r['receipt'];e=self.client.get('/api/targets/'+self.t['id']+'/evidence',{'receipt':receipt}).json();self.assertEqual({x['id'] for x in e['rows']},{'U1','U2'});s=self.client.get('/api/targets/'+self.t['id']+'/sources',{'receipt':receipt,'object_id':'U1'}).json();self.assertEqual(s['rows'][0]['row'],2);self.assertEqual(self.client.get('/api/targets/'+self.t['id']+'/sources',{'receipt':receipt,'object_id':'OUT'}).status_code,400)
    def test_followup_versions_audit_and_unchanged_facts(self):
        self.save_targets();r=self.client.get('/api/targets/'+self.t['id']).json();p=dict(version=0,status='责任岗位分析中',owner='模拟生产岗位',due_date='2026-10-06',note='核对模拟装配目标及差额原因',receipt=r['receipt']);before=list(Record.objects.values_list('values',flat=True));url='/api/targets/'+self.t['id']+'/follow-up';res=self.post(url,p);self.assertEqual(res.status_code,200);self.assertEqual(res.json()['follow_up']['version'],1);self.assertEqual(before,list(Record.objects.values_list('values',flat=True)));self.assertEqual(self.post(url,p).status_code,409);self.assertEqual(len(self.client.get('/api/targets/'+self.t['id']+'/history').json()['rows']),1)
    def test_read_roles_anonymous_and_csrf(self):
        self.save_targets();self.client.logout();self.assertEqual(self.client.get('/api/targets').status_code,401)
        for role in ['quality','operations','finance','viewer']:
            u=User.objects.create_user('read-'+role);u.groups.add(Group.objects.get_or_create(name=role)[0]);self.client.force_login(u);self.assertEqual(self.client.get('/api/targets').status_code,403);self.assertEqual(self.client.get('/api/records/kpi_targets').status_code,403)
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin);self.assertEqual(c.post('/api/targets/'+self.t['id']+'/follow-up','{}',content_type='application/json').status_code,403)
    def test_model_change_invalidates_receipt(self):
        self.save_targets();d=self.client.get('/api/targets').json();self.model.version+=1;self.model.save();self.assertEqual(self.client.get('/api/targets/export',{'receipt':d['receipt']}).status_code,409)

from django.core.exceptions import PermissionDenied
