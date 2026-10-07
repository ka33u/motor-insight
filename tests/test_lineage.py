import json,csv,io,uuid
from copy import deepcopy
from unittest.mock import patch
from django.test import SimpleTestCase,Client
from app import analytics,lineage,trace_cases
from app.schema import SCHEMAS
from app.models import TraceCase,Record,CodingRule,CodeAllocation,AuditEvent
from tests.test_platform import PlatformCase

def fixture():
    d={k:[] for k in SCHEMAS}
    d['materials']=[dict(id='MAT1',name='模拟铜线',unit='kg',category='铜线'),dict(id='MAT2',name='另一物料',unit='kg',category='铜线')]
    d['inventory_opening']=[dict(id='OPEN1',material_id='MAT1',lot='LOT001',location='A',qty=20,as_of='2026-09-01')]
    d['inventory_movements']=[dict(id='ISS1',material_id='MAT1',lot='LOT001',location='A',qty_signed=-10,work_order_id='W1',occurred='2026-09-02T08:00:00')]
    d['batches']=[dict(id=k,work_order_id='W1',kind='定子' if k=='B1' else '转子',qty=2,created='2026-09-02T07:00:00',status='装配领用') for k in ['B1','B2','OTHER']]
    d['products']=[dict(id='P1',family='YE4')];d['work_orders']=[dict(id='W1',product_id='P1')]
    d['units']=[dict(id='U1',work_order_id='W1',product_id='P1',assembly_at='2026-09-03T08:00:00',stator_batch='B1',rotor_batch='B2'),dict(id='U2',work_order_id='W1',product_id='P1',assembly_at='2026-09-03T08:00:00',stator_batch='B1',rotor_batch='B2'),dict(id='SAME-WO',work_order_id='W1',product_id='P1',assembly_at='2026-09-03T08:00:00',stator_batch='OTHER',rotor_batch='OTHER')]
    d['genealogy']=[dict(id='G1',parent_type='材料批次',parent_id='LOT001',child_type='生产批次',child_id='B1',qty=6,unit='kg',occurred='2026-09-02T08:00:00',work_order_id='W1'),dict(id='G2',parent_type='材料批次',parent_id='LOT001',child_type='生产批次',child_id='B2',qty=4,unit='kg',occurred='2026-09-02T08:00:00',work_order_id='W1')]
    for key,parent,child in [('G3','B1','U1'),('G4','B2','U1'),('G5','B1','U2')]:d['genealogy'].append(dict(id=key,parent_type='生产批次',parent_id=parent,child_type='整机',child_id=child,qty=1,unit='件',occurred='2026-09-03T08:00:00',work_order_id='W1'))
    d['customers']=[dict(id='C1',name='模拟客户')];d['orders']=[dict(id='O1',customer_id='C1')];d['order_lines']=[dict(id='L1',order_id='O1')]
    d['allocations']=[dict(id='A1',work_order_id='W1',order_line_id='L1',effective='2026-09-01',qty=3)]
    d['test_specs']=[dict(id='SPEC1',product_id='P1',version='A',mandatory=True,lsl=0,usl=2,unit='A')]
    d['test_sessions']=[dict(id='T1',unit_id='U1',spec_version='A',voided=False,tested='2026-09-03T09:00:00',attempt=1,complete=True,result='合格')]
    d['measurements']=[dict(id='M1',session_id='T1',spec_id='SPEC1',value=1,unit='A',result='合格')]
    d['releases']=[dict(id='R1',unit_id='U1',session_id='T1',released='2026-09-03T10:00:00',status='批准放行')]
    d['shipments']=[dict(id='S1',order_line_id='L1',shipped='2026-09-05T08:00:00',qty=1)]
    d['shipment_units']=[dict(id='PK1',shipment_id='S1',unit_id='U1')]
    return d

class LineageFactsTests(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def build(self):return lineage.Graph(self.d).build('material_lot','LOT001','MAT1')
    def test_two_paths_count_one_sn_and_do_not_expand_same_work_order(self):
        r=self.build();self.assertEqual([u['id'] for u in r['units']],['U1','U2']);self.assertEqual(r['summary']['unit_count'],2)
        self.assertEqual((r['summary']['shipped_count'],r['summary']['unshipped_count'],r['summary']['quality_attention_count']),(1,1,1));self.assertEqual(len(r['edges']),5);self.assertEqual(r['summary']['warning_count'],0)
    def test_shared_lot_material_is_not_silently_attributed(self):
        self.d['inventory_movements'].append({**self.d['inventory_movements'][0],'id':'ISS2','material_id':'MAT2'})
        r=self.build();self.assertEqual(r['summary']['uncertain_count'],2)
        with self.assertRaises(ValueError):lineage.Graph(self.d).build('material_lot','LOT001')
    def test_missing_explicit_edge_is_candidate_not_clear_or_dropped(self):
        self.d['genealogy']=[g for g in self.d['genealogy'] if g['child_id']!='U2']
        r=self.build();self.assertEqual(r['summary']['unit_count'],2);self.assertEqual(r['summary']['uncertain_count'],1)
        self.assertEqual(next(u for u in r['units'] if u['id']=='U2')['relation'],'档案候选，缺少谱系')
    def test_future_events_are_excluded(self):
        self.d['shipments'][0]['shipped']='2026-10-04T08:00:00';self.d['releases'][0]['released']='2026-10-04T08:00:00'
        self.d['genealogy'].append({**self.d['genealogy'][0],'id':'FUTURE','child_id':'FUTURE-BATCH','occurred':'2026-10-04T08:00:00'})
        r=self.build();self.assertEqual(r['summary']['shipped_count'],0);self.assertEqual(r['summary']['quality_attention_count'],2);self.assertNotIn('FUTURE',[e['id'] for e in r['edges']])
    def test_cycles_terminate_and_remain_uncertain(self):
        for key,a,b in [('CYCLE1','B1','B2'),('CYCLE2','B2','B1')]:self.d['genealogy'].append(dict(id=key,parent_type='生产批次',parent_id=a,child_type='生产批次',child_id=b,qty=1,unit='件',occurred='2026-09-02T09:00:00',work_order_id='W1'))
        r=self.build();self.assertEqual(r['summary']['unit_count'],2);self.assertEqual(r['summary']['uncertain_count'],2);self.assertTrue(any(w['kind']=='cycle' for w in r['warnings']))
    def test_quantity_mismatch_and_path_time_inversion_are_visible(self):
        self.d['genealogy'][0]['qty']=99;r=self.build();self.assertFalse(r['reconciliation'][0]['matched']);self.assertEqual(r['summary']['uncertain_count'],2)
        self.d=fixture();self.d['genealogy'][0]['occurred']='2026-09-04T08:00:00';r=self.build();self.assertTrue(any(w['kind']=='time_chain' for w in r['warnings']))
    def test_earlier_converging_path_is_not_lost_to_source_row_order(self):
        early={**self.d['genealogy'][0],'id':'EARLY','qty':3}
        self.d['genealogy'][0].update(qty=3,occurred='2026-09-04T08:00:00');self.d['genealogy'].append(early)
        self.assertEqual(self.build()['summary']['uncertain_count'],0)
        self.d['genealogy'].reverse();self.assertEqual(self.build()['summary']['uncertain_count'],0)
    def test_missing_whole_material_edge_does_not_infer_units_by_wo(self):
        self.d['genealogy']=[g for g in self.d['genealogy'] if g['parent_type']!='材料批次'];r=self.build();self.assertEqual(r['summary']['unit_count'],0);self.assertTrue(any(w['kind']=='missing_material_link' for w in r['warnings']))
        self.assertIn({'dataset':'inventory_movements','key':'ISS1'},r['sources'])
    def test_same_lot_in_separate_work_orders_keeps_material_scopes_distinct(self):
        self.d['inventory_movements'].append({**self.d['inventory_movements'][0],'id':'ISS2','material_id':'MAT2','work_order_id':'W2'})
        self.d['batches'].append({**self.d['batches'][0],'id':'B3','work_order_id':'W2'})
        self.d['units'].append({**self.d['units'][0],'id':'U3','work_order_id':'W2','stator_batch':'B3','rotor_batch':'B3'})
        self.d['genealogy'] += [{**self.d['genealogy'][0],'id':'G6','child_id':'B3','qty':10,'work_order_id':'W2'},{**self.d['genealogy'][2],'id':'G7','parent_id':'B3','child_id':'U3','work_order_id':'W2'}]
        graph=lineage.Graph(self.d)
        self.assertEqual([r['id'] for r in graph.build('material_lot','LOT001','MAT1')['units']],['U1','U2'])
        self.assertEqual([r['id'] for r in graph.build('material_lot','LOT001','MAT2')['units']],['U3'])
    def test_unknown_sn_and_batch_without_children_are_visible(self):
        self.d['genealogy'].append({**self.d['genealogy'][-1],'id':'MISSING','child_id':'UNKNOWN'})
        r=self.build();self.assertTrue(any(w['kind']=='missing_unit' for w in r['warnings']));self.assertEqual(r['summary']['unit_count'],2)
        leaf=lineage.Graph(self.d).build('batch','OTHER');self.assertTrue(any(w['kind']=='batch_leaf' for w in leaf['warnings']))
    def test_shared_order_assignment_and_new_test_do_not_create_false_certainty(self):
        self.d['allocations'].append({**self.d['allocations'][0],'id':'A2','order_line_id':'L2'})
        self.d['test_sessions'].append({**self.d['test_sessions'][0],'id':'T2','attempt':2,'tested':'2026-09-06T09:00:00'})
        self.d['measurements'].append({**self.d['measurements'][0],'id':'M2','session_id':'T2'})
        rows=self.build()['units'];u1=next(u for u in rows if u['id']=='U1');u2=next(u for u in rows if u['id']=='U2')
        self.assertFalse(u1['release_valid']);self.assertTrue(u1['shipped']);self.assertEqual(u1['order_ids'],['O1']);self.assertEqual(u2['order_ids'],[])
    def test_filters_and_unknown_root(self):
        r=self.build();rows,_=lineage.select(r,{'stage':'shipped'});self.assertEqual([x['id'] for x in rows],['U1'])
        self.assertEqual(lineage.select(r,{'q':'NO-SUCH-SN'})[0],[])
        with self.assertRaises(Record.DoesNotExist):lineage.Graph(self.d).build('batch','MISSING')
        self.assertEqual(lineage.Graph(self.d).search('material_lot','模拟铜线')['total'],1)

class LineageApiTests(PlatformCase):
    def setUp(self):
        super().setUp();self.d=fixture()
        for ds,rows in self.d.items():
            for row in rows:self.record(ds,row)
        analytics._tables.cache_clear();lineage.graph.cache_clear();self.addCleanup(analytics._tables.cache_clear);self.addCleanup(lineage.graph.cache_clear)
        CodingRule.objects.create(key='trace_case',name='批次排查',prefix='PC',date_format='%Y%m%d',width=5,separator='-',reset_period='day')
        self.client.force_login(self.quality)
    def payload(self):return {'request_id':str(uuid.uuid4()),'root':{'kind':'material_lot','id':'LOT001','material_id':'MAT1'},'data_revision':list(analytics.revision()),'title':'模拟批次排查','owner':'模拟质量岗位','due_date':'2026-10-06','note':'根据模拟材料批次核查关联范围，不发送客户通知。'}
    def create(self):
        r=self.post('/api/trace-cases',self.payload());self.assertEqual(r.status_code,200,r.content);return r.json()
    def test_auth_roles_and_no_cost_fields(self):
        self.assertEqual(Client().get('/api/lineage/search').status_code,401)
        r=self.client.get('/api/lineage?kind=material_lot&id=LOT001&material_id=MAT1');self.assertEqual(r.status_code,200);self.assertNotIn('cents',r.content.decode())
        self.quality.groups.clear();self.assertEqual(self.post('/api/trace-cases',self.payload()).status_code,401)
        self.client.force_login(self.quality);self.assertEqual(self.post('/api/trace-cases',self.payload()).status_code,403)
    def test_snapshot_idempotency_original_sources_and_no_business_write(self):
        before=Record.objects.count();p=self.payload();a=self.post('/api/trace-cases',p).json();b=self.post('/api/trace-cases',p).json();self.assertEqual(a['id'],b['id']);self.assertEqual(CodeAllocation.objects.count(),1)
        c=TraceCase.objects.get(pk=a['id']);self.assertEqual(c.snapshot_hash,trace_cases.digest(c.snapshot));self.assertEqual(Record.objects.count(),before)
        self.assertTrue(any(s.get('filename')=='unit-test.xlsx' for s in c.snapshot['source_manifest']))
        self.assertEqual(self.post('/api/trace-cases',{**p,'title':'变更请求'}).status_code,409)
    def test_stale_data_rejected_and_audit_rolls_back_snapshot_and_code(self):
        p=self.payload();p['data_revision']=[0,'old'];self.assertEqual(self.post('/api/trace-cases',p).status_code,409)
        with patch('app.trace_cases.AuditEvent.objects.create',side_effect=RuntimeError('audit failed')):
            with self.assertRaises(RuntimeError):self.post('/api/trace-cases',self.payload())
        self.assertEqual(TraceCase.objects.count(),0);self.assertEqual(CodeAllocation.objects.count(),0)
    def test_case_updates_version_only_and_snapshot_is_immutable(self):
        c=self.create();before=TraceCase.objects.get(pk=c['id']).snapshot
        changes={k:c[k] for k in ['version','title','owner','due_date','status','note']};changes['status']='待业务核验'
        r=self.post('/api/trace-cases/'+c['id'],changes);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['version'],2)
        self.assertEqual(self.post('/api/trace-cases/'+c['id'],changes).status_code,409)
        self.assertEqual(TraceCase.objects.get(pk=c['id']).snapshot,before)
        self.assertEqual(self.post('/api/trace-cases/'+c['id'],{**changes,'version':2,'snapshot':{}}).status_code,400)
    def test_snapshot_comparison_detects_changes_without_overwrite(self):
        c=self.create();old=TraceCase.objects.get(pk=c['id']).snapshot_hash
        r=Record.objects.get(dataset='test_sessions',business_key='T1');r.values['voided']=True;r.save()
        delta=self.client.get('/api/trace-cases/'+c['id']+'/compare').json();self.assertEqual(delta['changed_count'],1);self.assertTrue(delta['snapshot_unchanged'])
        self.assertEqual(TraceCase.objects.get(pk=c['id']).snapshot_hash,old)
        saved=self.client.get('/api/lineage?case_id='+c['id']).json();self.assertTrue(saved['units'][0]['release_valid'])
    def test_membership_change_and_source_revisions_preserve_snapshot(self):
        c=self.create();original=TraceCase.objects.get(pk=c['id']).snapshot
        old_ref=next(r for r in original['source_manifest'] if r['dataset']=='units' and r['key']=='U1')
        unit=Record.objects.get(dataset='units',business_key='U1');unit.revision+=1;unit.save()
        Record.objects.filter(dataset='units',business_key='U2').delete()
        self.record('units',{**self.d['units'][0],'id':'U3'})
        self.record('genealogy',{**self.d['genealogy'][-1],'id':'G8','child_id':'U3'})
        delta=self.client.get('/api/trace-cases/'+c['id']+'/compare').json()
        self.assertEqual(delta['added'],['U3']);self.assertEqual(delta['removed'],['U2']);self.assertTrue(delta['snapshot_unchanged'])
        frozen=TraceCase.objects.get(pk=c['id']).snapshot
        self.assertEqual(next(r for r in frozen['source_manifest'] if r['dataset']=='units' and r['key']=='U1'),old_ref)
        self.assertEqual(frozen,original)
    def test_coordination_role_cannot_close_without_quality_verification(self):
        c=self.create();changes={k:c[k] for k in ['version','title','owner','due_date','status','note']};changes['status']='演练已结案'
        from django.contrib.auth.models import User,Group
        ops=User.objects.create(username='lineage_ops');ops.groups.add(Group.objects.get_or_create(name='operations')[0]);self.client.force_login(ops)
        self.assertEqual(self.post('/api/trace-cases/'+c['id'],changes).status_code,403)
        self.client.force_login(self.quality);self.assertEqual(self.post('/api/trace-cases/'+c['id'],changes).status_code,200)
    def test_csv_filter_matches_table_and_escapes_formulas(self):
        r=Record.objects.get(dataset='customers',business_key='C1');r.values['name']='=UNTRUSTED()';r.save()
        q='kind=material_lot&id=LOT001&material_id=MAT1&stage=shipped'
        board=self.client.get('/api/lineage?'+q).json();data=list(csv.reader(io.StringIO(self.client.get('/api/lineage/export?'+q).content.decode('utf-8-sig'))))
        self.assertEqual(len(data)-4,board['unit_total']);self.assertEqual(data[4][10],"'=UNTRUSTED()")
    def test_path_pagination_evidence_and_csrf(self):
        q='kind=material_lot&id=LOT001&material_id=MAT1';r=self.client.get('/api/lineage/unit/U1?'+q).json();self.assertEqual(len(r['path']),2)
        self.assertEqual(self.client.get('/api/lineage/unit/SAME-WO?'+q).status_code,404)
        self.assertEqual(self.client.get('/api/lineage?'+q+'&page=2').json()['units'],[])
        c=self.create();e=self.client.get('/api/lineage/evidence?case_id='+c['id']).json();self.assertTrue(e['frozen']);self.assertFalse(e['can_download_original'])
        client=Client(enforce_csrf_checks=True);client.force_login(self.admin);self.assertEqual(client.post('/api/trace-cases','{}',content_type='application/json').status_code,403)
