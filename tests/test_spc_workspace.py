import csv,io,json,uuid
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth.models import User,Group
from django.core.exceptions import ValidationError
from django.test import Client
from app.models import SPCAnalysisView,SPCResultSnapshot,Topic,Record,AuditEvent,ImportRow
from app.ingestion import fingerprint
from . import test_spc as sources
from .test_platform import PlatformCase

class SPCWorkspaceTests(PlatformCase):
    def setUp(self):
        super().setUp();self.s,self.p,self.spec,self.units=sources.fixture(n=40)
        self.record('spc_studies',self.s);self.record('test_specs',self.spec)
        self.record('products',dict(id='P1',family='SIM',price_cents=900));self.record('equipment',dict(id='D1',name='模拟设备',cost_cents=100))
        self.record('employees',dict(id='E1',name='合成人员'))
        for u in self.units.values():self.record('units',u)
        for p in self.p:self.record('spc_observations',p)
        self.client.force_login(self.quality);self.t=Topic.objects.create(name='合成质量专题',owner='system',is_public=True)
    def d(self):
        response=self.client.get('/api/spc/S1');self.assertEqual(response.status_code,200,response.content[:300]);return response.json()
    def view_payload(self):
        return dict(request_id=str(uuid.uuid4()),code='SPC.SIM.R.0001',name='受控试验视角',note='合成试验定义与来源演练',study_id='S1',receipt=self.d()['receipt'],
                    display=dict(show_spec=True,decimals=6),topic_id=self.t.pk)
    def save(self,data=None):
        response=self.post('/api/spc-analysis-views',data or self.view_payload());self.assertEqual(response.status_code,200,response.content[:300]);return response.json()['view']
    def snapshot_payload(self,v):
        run=self.client.get('/api/spc-analysis-views/'+v['id']+'/run').json()
        return dict(request_id=str(uuid.uuid4()),view_id=v['id'],revision=v['revision'],receipt=run['receipt'],name='合成受控试验快照',note='保留试算和来源用于后续复查')
    def freeze(self,v=None,data=None):
        v=v or self.save();response=self.post('/api/spc-result-snapshots',data or self.snapshot_payload(v));self.assertEqual(response.status_code,200,response.content[:300]);return response.json()['snapshot']
    def frozen(self,s,query=None):return self.client.get('/api/spc-result-snapshots/'+s['id'],query or {})
    def update_fact(self,ds,key,fields):
        r=Record.objects.get(dataset=ds,business_key=key);old=r.source_row;r.values.update(fields)
        row=self.row(ds,r.values,'committed');row.row_number=old.row_number+1;row.save()
        r.source_row=row;r.record_hash=row.record_hash;r.revision+=1;r.save();return r
    def test_save_definition_replay_and_no_source_changes(self):
        before=(Record.objects.count(),self.batch.rows.count());data=self.view_payload();v=self.save(data);a=AuditEvent.objects.count()
        replay=self.post('/api/spc-analysis-views',data);self.assertTrue(replay.json()['repeated']);self.assertEqual(AuditEvent.objects.count(),a)
        self.assertEqual(before,(Record.objects.count(),self.batch.rows.count()));self.assertEqual(v['definition']['study_contract']['baseline_end'],20)
        self.assertNotIn('points',v['definition']);self.assertNotIn('limits',v['definition'])
    def test_same_request_cannot_change_code_or_actor(self):
        data=self.view_payload();self.save(data);data['name']='不同视角';self.assertEqual(self.post('/api/spc-analysis-views',data).status_code,409)
        self.client.force_login(self.admin);self.assertEqual(self.post('/api/spc-analysis-views',data).status_code,409)
    def test_codes_are_personal_unique_and_strict(self):
        self.save()
        self.assertEqual(self.post('/api/spc-analysis-views',self.view_payload()).status_code,400)
        for value in ['spc.lower','=FORMULA','A','含中文编码']:
            p=self.view_payload();p['code']=value;self.assertEqual(self.post('/api/spc-analysis-views',p).status_code,400)
        self.client.force_login(self.admin);self.save();self.assertEqual(SPCAnalysisView.objects.count(),2)
    def test_invalid_display_baseline_override_and_missing_receipt_rejected(self):
        for value in [{'show_spec':'false','decimals':6},{'show_spec':True,'decimals':3},{'show_spec':True,'decimals':True},{'show_spec':True,'decimals':6,'baseline_end':10}]:
            p=self.view_payload();p['display']=value;self.assertEqual(self.post('/api/spc-analysis-views',p).status_code,400)
        p=self.view_payload();p['receipt']='';self.assertEqual(self.post('/api/spc-analysis-views',p).status_code,400)
    def test_expired_source_receipt_does_not_save_view(self):
        with patch('django.core.signing.time.time',return_value=0):p=self.view_payload()
        self.assertEqual(self.post('/api/spc-analysis-views',p).status_code,409);self.assertEqual(SPCAnalysisView.objects.count(),0)
    def test_all_six_roles_can_save_own_nonfinancial_view(self):
        for role in ['admin','analyst','quality','operations','finance','viewer']:
            u=User.objects.filter(username=role).first() or User.objects.create_user(role);g,_=Group.objects.get_or_create(name=role);u.groups.add(g);self.client.force_login(u);self.save()
        self.assertEqual(SPCAnalysisView.objects.count(),6)
    def test_private_view_not_readable_by_admin_or_other_user(self):
        v=self.save();self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/api/spc-analysis-views').json()['total'],0);self.assertEqual(self.client.get('/api/spc-analysis-views/'+v['id']).status_code,404)
        self.assertEqual(self.client.get('/api/spc-analysis-views/'+v['id']+'/run').status_code,404)
    def test_topic_association_does_not_change_shared_topic(self):
        old=deepcopy((self.t.layout,self.t.version,self.t.updated_at));v=self.save();self.t.refresh_from_db();self.assertEqual((self.t.layout,self.t.version,self.t.updated_at),old)
        rows=self.client.get('/api/spc-analysis-views',{'topic_id':self.t.pk}).json()['rows'];self.assertEqual(rows[0]['id'],v['id'])
    def test_unreadable_topic_cannot_be_bound(self):
        self.t.is_public=False;self.t.save();p=self.view_payload();self.assertEqual(self.post('/api/spc-analysis-views',p).status_code,404)
    def test_update_version_optimistic_lock_and_frozen_definition(self):
        v=self.save();s=self.freeze(v);data=self.view_payload();data.pop('request_id');data['revision']=v['revision'];data['name']='调整显示名称';data['display']['decimals']=8
        r=self.post('/api/spc-analysis-views/'+v['id'],data);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['view']['revision'],2)
        self.assertEqual(self.post('/api/spc-analysis-views/'+v['id'],data).status_code,409)
        frozen=self.frozen(s).json();self.assertEqual(frozen['view']['name'],'受控试验视角');self.assertEqual(frozen['view']['definition']['display']['decimals'],6)
    def test_archive_blocks_live_capture_but_keeps_frozen(self):
        v=self.save();data=self.snapshot_payload(v);s=self.freeze(v,data);response=self.post('/api/spc-analysis-views/'+v['id']+'/archive',dict(revision=1,archived=True));self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get('/api/spc-analysis-views/'+v['id']+'/run').status_code,409);self.assertEqual(self.frozen(s).status_code,200)
        self.assertEqual(self.client.get('/api/spc-analysis-views').json()['total'],0);self.assertEqual(self.client.get('/api/spc-analysis-views',{'archived':'1'}).json()['total'],1)
        replay=self.post('/api/spc-result-snapshots',data);self.assertTrue(replay.json()['repeated'])
    def test_view_detects_plan_spec_and_rule_drift(self):
        for ds,key,fields in [('spc_studies','S1',dict(baseline_end=21)),('test_specs','R1',dict(usl=12))]:
            v=self.save();self.update_fact(ds,key,fields);self.assertEqual(self.client.get('/api/spc-analysis-views/'+v['id']+'/run').status_code,409)
            SPCAnalysisView.objects.all().delete()
        v=self.save()
        with patch('app.spc.rule_hash',return_value='different'):self.assertEqual(self.client.get('/api/spc-analysis-views/'+v['id']+'/run').status_code,409)
    def test_monitoring_data_change_runs_same_plan_with_new_source_receipt(self):
        v=self.save();self.update_fact('spc_observations','O40',dict(value=18));d=self.client.get('/api/spc-analysis-views/'+v['id']+'/run').json()
        self.assertEqual(d['limits']['center'],10);self.assertTrue(d['chart_points'][-1]['i_signal'])
    def test_snapshot_freezes_all_points_and_sources_not_visible_page(self):
        s=self.freeze();d=self.frozen(s,{'page':2}).json();self.assertEqual(len(d['rows']),15);self.assertEqual(len(d['chart_points']),40);self.assertEqual(d['snapshot']['observations'],40)
        saved=SPCResultSnapshot.objects.get(pk=s['id']);self.assertEqual(len(saved.payload['result']['points']),40);self.assertTrue(saved.payload['rule_sources'])
        product=next(r for r in saved.payload['sources'] if r['dataset']=='products');self.assertNotIn('price_cents',product['values'])
    def test_frozen_reads_do_not_follow_current_source_pointer(self):
        s=self.freeze();old=self.frozen(s).json();self.update_fact('spc_observations','O1',dict(value=19));new=self.frozen(s).json()
        self.assertEqual(old['chart_points'],new['chart_points']);d=self.client.get('/api/spc-result-snapshots/'+s['id']+'/points/O1',{'receipt':new['receipt']}).json()
        self.assertEqual(d['row']['value'],9);source=next(r for r in d['sources'] if r['dataset']=='spc_observations' and r['key']=='O1');self.assertEqual(source['revision'],1)
    def test_frozen_reads_survive_current_fact_deletion(self):
        s=self.freeze();Record.objects.filter(dataset='spc_studies',business_key='S1').delete();self.assertEqual(self.frozen(s).status_code,200)
        comparison=self.client.get('/api/spc-result-snapshots/'+s['id']+'/compare-current').json();self.assertEqual(comparison['state'],'source_missing')
    def test_paused_analysis_can_be_frozen_with_reasons_not_fake_limits(self):
        self.update_fact('spc_studies','S1',dict(baseline_end=6));s=self.freeze();d=self.frozen(s).json();self.assertEqual(d['state'],'paused');self.assertIsNone(d['limits']);self.assertTrue(d['issues'])
    def test_snapshot_request_replay_after_expiry_is_idempotent(self):
        v=self.save();data=self.snapshot_payload(v);s=self.freeze(v,data);counts=(SPCResultSnapshot.objects.count(),AuditEvent.objects.count())
        with patch('django.core.signing.time.time',return_value=1e12):response=self.post('/api/spc-result-snapshots',data)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['snapshot']['id'],s['id']);self.assertTrue(response.json()['repeated']);self.assertEqual(counts,(SPCResultSnapshot.objects.count(),AuditEvent.objects.count()))
    def test_snapshot_request_cannot_change_note_or_actor(self):
        v=self.save();data=self.snapshot_payload(v);self.freeze(v,data);data['note']='更换申请的内容';self.assertEqual(self.post('/api/spc-result-snapshots',data).status_code,409)
        self.client.force_login(self.admin);self.assertEqual(self.post('/api/spc-result-snapshots',data).status_code,409)
    def test_frozen_private_access_even_admin(self):
        s=self.freeze();self.client.force_login(self.admin);self.assertEqual(self.frozen(s).status_code,404);self.assertEqual(self.client.get('/api/spc-result-snapshots').json()['total'],0)
    def test_snapshot_metadata_or_payload_tamper_detected(self):
        s=self.freeze();SPCResultSnapshot.objects.filter(pk=s['id']).update(name='篡改标题');self.assertEqual(self.frozen(s).status_code,409)
        row=SPCResultSnapshot.objects.get(pk=s['id']);row.name=s['name'];row.payload['result']['limits']['center']=0;SPCResultSnapshot.objects.filter(pk=row.pk).update(name=row.name,payload=row.payload)
        self.assertEqual(self.frozen(s).status_code,409)
    def test_model_save_method_cannot_overwrite_snapshot(self):
        s=self.freeze();row=SPCResultSnapshot.objects.get(pk=s['id'])
        with self.assertRaises(ValidationError):row.save()
    def test_snapshot_receipts_expire_cross_user_or_payload_change(self):
        s=self.freeze();d=self.frozen(s).json();url='/api/spc-result-snapshots/'+s['id']+'/sources'
        with patch('django.core.signing.time.time',return_value=1e12):self.assertEqual(self.client.get(url,{'receipt':d['receipt']}).status_code,409)
        self.client.force_login(self.admin);self.assertEqual(self.client.get(url,{'receipt':d['receipt']}).status_code,404)
    def test_private_snapshot_stops_when_topic_becomes_unreadable(self):
        s=self.freeze();self.t.is_public=False;self.t.save();self.assertEqual(self.frozen(s).status_code,404)
        row=self.client.get('/api/spc-result-snapshots').json()['rows'][0];self.assertFalse(row['available']);self.assertNotIn('name',row)
    def test_frozen_csv_and_json_complete_and_formula_safe(self):
        v=self.save();data=self.snapshot_payload(v);data['name']='=模拟名称';s=self.freeze(v,data);d=self.frozen(s).json();url='/api/spc-result-snapshots/'+s['id']+'/export'
        r=self.client.get(url,{'receipt':d['receipt'],'page':2});rows=list(csv.reader(io.StringIO(r.content.decode('utf-8-sig'))));self.assertEqual(len(rows),45);self.assertEqual(rows[-1][0],'O40');self.assertIn("'=模拟名称",rows[0])
        r=self.client.get(url,{'receipt':d['receipt'],'format':'json'});self.assertIn('.json',r['Content-Disposition']);self.assertEqual(len(json.loads(r.content)['payload']['result']['points']),40)
    def test_frozen_source_and_csv_reads_no_extra_business_changes(self):
        s=self.freeze();d=self.frozen(s).json();before=(Record.objects.count(),self.batch.rows.count(),AuditEvent.objects.count())
        self.client.get('/api/spc-result-snapshots/'+s['id']+'/sources',{'receipt':d['receipt']});self.client.get('/api/spc-result-snapshots/'+s['id']+'/points/O30',{'receipt':d['receipt']})
        self.assertEqual(before,(Record.objects.count(),self.batch.rows.count(),AuditEvent.objects.count()))
    def test_original_requires_import_permission_even_owner(self):
        s=self.freeze();d=self.frozen(s).json();source=self.client.get('/api/spc-result-snapshots/'+s['id']+'/points/O30',{'receipt':d['receipt']}).json()['sources'][0]
        row=next(r for r in SPCResultSnapshot.objects.get(pk=s['id']).payload['sources'] if r['dataset']=='spc_observations')
        response=self.client.get('/api/spc-result-snapshots/'+s['id']+'/original/'+str(row['source_row_id']),{'receipt':d['receipt']});self.assertEqual(response.status_code,403)
    def test_original_uses_frozen_source_row_after_current_replacement(self):
        self.client.force_login(self.admin)
        with TemporaryDirectory() as folder,self.settings(BASE_DIR=Path(folder)):
            archive=Path(folder)/'data/imports';archive.mkdir(parents=True);p=archive/'sample.xlsx';p.write_bytes(b'synthetic archive bytes')
            import hashlib
            self.batch.file_path=str(p);self.batch.file_hash=hashlib.sha256(p.read_bytes()).hexdigest();self.batch.save();s=self.freeze();d=self.frozen(s).json()
            saved=SPCResultSnapshot.objects.get(pk=s['id']);row=next(r for r in saved.payload['sources'] if r['dataset']=='spc_observations' and r['key']=='O1')
            self.update_fact('spc_observations','O1',dict(value=18));url='/api/spc-result-snapshots/'+s['id']+'/original/'+str(row['source_row_id'])
            response=self.client.get(url,{'receipt':d['receipt']});self.assertEqual(response.status_code,200);self.assertEqual(response.content,b'synthetic archive bytes')
            p.write_bytes(b'corrupt bytes');self.assertEqual(self.client.get(url,{'receipt':d['receipt']}).status_code,400)
    def test_compare_monitoring_change_baseline_unchanged(self):
        s=self.freeze();self.update_fact('spc_observations','O40',dict(value=19));d=self.client.get('/api/spc-result-snapshots/'+s['id']+'/compare-current').json()
        self.assertEqual(d['state'],'data_changed');self.assertTrue(d['pointwise_comparable']);self.assertFalse(d['baseline_evidence_changed']);self.assertFalse(d['limits_changed']);self.assertFalse(d['causal_claim'])
        self.assertEqual(d['rows'][0]['before']['value'],11);self.assertEqual(d['rows'][0]['current']['value'],19)
    def test_compare_baseline_correction_keeps_both_limits(self):
        s=self.freeze();self.update_fact('spc_observations','O1',dict(value=15));d=self.client.get('/api/spc-result-snapshots/'+s['id']+'/compare-current').json()
        self.assertEqual(d['state'],'baseline_evidence_changed');self.assertTrue(d['limits_changed']);self.assertEqual(d['limits_before']['center'],10)
    def test_compare_plan_or_rule_change_not_same_definition_delta(self):
        s=self.freeze();self.update_fact('spc_studies','S1',dict(baseline_end=22));d=self.client.get('/api/spc-result-snapshots/'+s['id']+'/compare-current').json()
        self.assertEqual(d['state'],'definitions_changed');self.assertFalse(d['pointwise_comparable']);self.assertIn('study_contract',d['definition_changes'])
    def test_compare_same_observations_and_receipt_change(self):
        s=self.freeze();url='/api/spc-result-snapshots/'+s['id']+'/compare-current';d=self.client.get(url).json();self.assertEqual(d['state'],'same_observations');self.assertEqual(d['rows'],[])
        self.update_fact('spc_observations','O40',dict(value=18));self.assertEqual(self.client.get(url,{'receipt':d['receipt']}).status_code,409)
    def test_compare_add_and_missing_objects_are_not_zero(self):
        s=self.freeze();Record.objects.filter(dataset='spc_observations',business_key='O40').delete();d=self.client.get('/api/spc-result-snapshots/'+s['id']+'/compare-current').json()
        missing=next(r for r in d['rows'] if r['id']=='O40');self.assertIsNone(missing['current']);self.assertIn('missing_current',missing['kinds'])
    def test_save_snapshot_audit_failure_rolls_back(self):
        v=self.save();data=self.snapshot_payload(v);before=SPCResultSnapshot.objects.count()
        with patch('app.spc_workspace.AuditEvent.objects.create',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):self.post('/api/spc-result-snapshots',data)
        self.assertEqual(SPCResultSnapshot.objects.count(),before)
    def test_view_update_audit_failure_rolls_back(self):
        v=self.save();data=self.view_payload();data.pop('request_id');data['revision']=1;data['name']='不能残留的更新'
        with patch('app.spc_workspace.AuditEvent.objects.create',side_effect=RuntimeError('audit failure')):
            with self.assertRaises(RuntimeError):self.post('/api/spc-analysis-views/'+v['id'],data)
        row=SPCAnalysisView.objects.get(pk=v['id']);self.assertEqual(row.revision,1);self.assertEqual(row.name,v['name'])
    def test_unknown_query_and_methods_do_not_mutate(self):
        v=self.save();s=self.freeze(v)
        self.assertEqual(self.client.get('/api/spc-result-snapshots/'+s['id'],{'as_of':'2026-01-01'}).status_code,400)
        self.assertEqual(self.client.post('/api/spc-result-snapshots/'+s['id']).status_code,405)
        self.assertEqual(self.client.delete('/api/spc-analysis-views/'+v['id']).status_code,405)
    def test_csrf_required_for_view_snapshot_and_archive(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.quality)
        self.assertEqual(client.post('/api/spc-analysis-views',json.dumps(self.view_payload()),content_type='application/json').status_code,403)
