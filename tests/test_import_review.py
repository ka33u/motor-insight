import json,tempfile,hashlib
from pathlib import Path
from unittest.mock import patch
from django.test import Client
from app.models import ImportBatch,ImportRow,Record,ImportDecision,AuditEvent
from app.ingestion import fingerprint,commit_batch,stage_file
from django.conf import settings
from app.import_review import decide,snapshot
from app.analytics import revision
from tests.test_platform import PlatformCase

class ConflictReviewTests(PlatformCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.admin)
        self.original=self.record('departments',{'id':'D01','name':'生产部门','owner':'原负责人'})
        self.batch.status='committed';self.batch.save()
        self.review_batch=ImportBatch.objects.create(filename='更正.xlsx',file_hash='c',file_path='none',status='staged')
        self.candidate=self.proposal('新负责人')
        self.url=f'/api/imports/{self.review_batch.pk}/rows/{self.candidate.pk}/review'
    def proposal(self,owner):
        values={**self.original.values,'owner':owner}
        return ImportRow.objects.create(batch=self.review_batch,sheet='部门档案',row_number=2,dataset='departments',business_key='D01',raw={'部门编码':'D01','负责人岗位':owner},normalized=values,record_hash=fingerprint(values),status='conflict',issues=[{'message':'主键内容冲突'}])
    def payload(self,action='replace',row=None):
        row=row or self.candidate;self.original.refresh_from_db()
        return {'action':action,'reason':'依据模拟更正单核对后批准','expected':{'record_id':self.original.pk,'revision':self.original.revision,'hash':self.original.record_hash,'candidate_hash':row.record_hash}}
    def test_comparison_shows_changed_fields_and_source(self):
        response=self.client.get(self.url);self.assertEqual(response.status_code,200);d=response.json()
        self.assertEqual([f['name'] for f in d['fields'] if f['changed']],['owner'])
        self.assertEqual(d['comparison_base']['values']['owner'],'原负责人');self.assertEqual(d['candidate']['source']['filename'],'更正.xlsx');self.assertTrue(d['can_review'])
    def test_plain_commit_never_overwrites_conflict(self):
        result=commit_batch(self.review_batch.pk);self.original.refresh_from_db()
        self.assertEqual(result.status,'partial');self.assertEqual(self.original.values['owner'],'原负责人');self.assertFalse(ImportDecision.objects.exists())
    def test_replace_retains_snapshots_and_advances_revision_and_cache(self):
        before=revision();raw=self.candidate.raw.copy();response=self.post(self.url,self.payload());self.assertEqual(response.status_code,200,response.content)
        self.original.refresh_from_db();self.candidate.refresh_from_db();decision=ImportDecision.objects.get()
        self.assertEqual((self.original.revision,self.original.values['owner'],self.original.source_row_id),(2,'新负责人',self.candidate.pk))
        self.assertEqual(decision.before['values']['owner'],'原负责人');self.assertEqual(decision.after['revision'],2)
        self.assertEqual(self.candidate.status,'replaced');self.assertEqual(self.candidate.raw,raw);self.assertNotEqual(revision(),before)
        self.assertEqual(Record.objects.count(),1);self.assertEqual(AuditEvent.objects.filter(action='import.conflict.replace').count(),1)
    def test_keep_retains_current_source_and_closes_review(self):
        before=snapshot(self.original);r=self.post(self.url,self.payload('keep'));self.assertEqual(r.status_code,200,r.content)
        self.original.refresh_from_db();self.review_batch.refresh_from_db();self.candidate.refresh_from_db()
        self.assertEqual(snapshot(self.original),before);self.assertEqual(self.candidate.status,'kept');self.assertEqual(self.review_batch.status,'committed');self.assertEqual(self.review_batch.summary['kept'],1)
    def test_same_submission_is_idempotent_but_different_decision_is_not(self):
        payload=self.payload();first=self.post(self.url,payload);second=self.post(self.url,payload)
        self.assertEqual(first.status_code,200);self.assertEqual(second.status_code,200);self.assertTrue(second.json()['repeated']);self.assertEqual(ImportDecision.objects.count(),1)
        payload['action']='keep';self.assertEqual(self.post(self.url,payload).status_code,409)
    def test_stale_form_cannot_overwrite_later_approved_change(self):
        stale=self.payload();other=self.proposal('另一份经核验负责人')
        decide(self.review_batch.pk,other.pk,'admin',self.payload(row=other))
        r=self.post(self.url,stale);self.assertEqual(r.status_code,409);self.original.refresh_from_db();self.candidate.refresh_from_db()
        self.assertEqual(self.original.values['owner'],'另一份经核验负责人');self.assertEqual(self.candidate.status,'conflict')
    def test_candidate_repair_invalidates_old_review_token(self):
        stale=self.payload();values={**self.candidate.normalized,'owner':'修复后的负责人'}
        url=f'/api/imports/{self.review_batch.pk}/rows/{self.candidate.pk}/repair'
        r=self.post(url,{'expected_row_hash':self.candidate.record_hash,'values':values});self.assertEqual(r.status_code,200,r.content)
        self.assertEqual(r.json()['status'],'conflict');self.assertEqual(self.post(self.url,stale).status_code,409)
        self.assertEqual(self.post(url,{'expected_row_hash':self.candidate.record_hash,'values':values}).status_code,409)
    def test_approval_requires_reason_and_exact_version_token(self):
        for mutate in [lambda p:p.update(reason=''),lambda p:p.update(expected={}),lambda p:p['expected'].update(record_id=True)]:
            payload=self.payload();mutate(payload);self.assertEqual(self.post(self.url,payload).status_code,400)
        self.assertFalse(ImportDecision.objects.exists())
    def test_replace_revalidates_schema_and_primary_key(self):
        self.candidate.normalized['owner']=None;self.candidate.record_hash=fingerprint(self.candidate.normalized);self.candidate.save()
        self.assertEqual(self.post(self.url,self.payload()).status_code,400)
        self.candidate.normalized={'id':'D02','name':'生产部门','owner':'错误编码'};self.candidate.record_hash=fingerprint(self.candidate.normalized);self.candidate.save()
        self.assertEqual(self.post(self.url,self.payload()).status_code,400);self.assertEqual(Record.objects.count(),1)
    def test_transaction_rolls_back_when_audit_cannot_be_written(self):
        with patch('app.import_review.AuditEvent.objects.create',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):decide(self.review_batch.pk,self.candidate.pk,'admin',self.payload())
        self.original.refresh_from_db();self.candidate.refresh_from_db()
        self.assertEqual(self.original.revision,1);self.assertEqual(self.candidate.status,'conflict');self.assertFalse(ImportDecision.objects.exists())
    def test_historical_batches_cannot_be_repaired_or_approved(self):
        self.review_batch.status='superseded';self.review_batch.save()
        self.assertEqual(self.post(self.url,self.payload()).status_code,409)
        r=self.post(f'/api/imports/{self.review_batch.pk}/rows/{self.candidate.pk}/repair',{'expected_row_hash':self.candidate.record_hash,'values':self.candidate.normalized});self.assertEqual(r.status_code,409)
    def test_role_permissions_and_csrf_apply_to_review_and_history(self):
        self.client.force_login(self.quality)
        for url in [self.url,f'/api/record-history/{self.original.pk}',f'/api/imports/{self.batch.pk}/file']:self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.post(self.url,self.payload()).status_code,403)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.admin)
        self.assertEqual(csrf.post(self.url,json.dumps(self.payload()),content_type='application/json').status_code,403)
    def test_history_preserves_multiple_versions(self):
        self.post(self.url,self.payload());other=self.proposal('第二次更正负责人');self.review_batch.status='staged';self.review_batch.save()
        decide(self.review_batch.pk,other.pk,'admin',self.payload(row=other))
        r=self.client.get(f'/api/record-history/{self.original.pk}').json()
        self.assertEqual(r['current']['revision'],3);self.assertEqual([c['after']['revision'] for c in r['changes']],[3,2]);self.assertEqual(r['changes'][1]['before']['values']['owner'],'原负责人')
    def test_archived_file_download_is_exact_and_path_bounded(self):
        with tempfile.TemporaryDirectory() as directory,self.settings(BASE_DIR=Path(directory)):
            archive=Path(directory)/'data/imports';archive.mkdir(parents=True);path=archive/'test.xlsx';path.write_bytes(b'archived source bytes')
            self.batch.file_path=str(path);self.batch.file_hash=hashlib.sha256(path.read_bytes()).hexdigest();self.batch.save();r=self.client.get(f'/api/imports/{self.batch.pk}/file')
            self.assertEqual(r.status_code,200);self.assertEqual(b''.join(r.streaming_content),b'archived source bytes')
            path.write_bytes(b'changed archive');self.assertEqual(self.client.get(f'/api/imports/{self.batch.pk}/file').status_code,400)
            self.batch.file_path=str(Path(directory)/'outside.xlsx');self.batch.save();self.assertEqual(self.client.get(f'/api/imports/{self.batch.pk}/file').status_code,400)
    def test_replacement_rechecks_foreign_keys(self):
        old={'id':'E00001','name':'模拟员工','department_id':'D01','role':'操作员','skill_level':'初级','hourly_cents':5000,'active':True}
        employee=self.record('employees',old);values={**old,'department_id':'D99'}
        row=ImportRow.objects.create(batch=self.review_batch,sheet='人员档案',row_number=2,dataset='employees',business_key=old['id'],raw=values,normalized=values,record_hash=fingerprint(values),status='conflict')
        payload={'action':'replace','reason':'核对模拟人员更正申请','expected':{'record_id':employee.pk,'revision':1,'hash':employee.record_hash,'candidate_hash':row.record_hash}}
        r=self.post(f'/api/imports/{self.review_batch.pk}/rows/{row.pk}/review',payload);self.assertEqual(r.status_code,400);employee.refresh_from_db();self.assertEqual(employee.values['department_id'],'D01')
    def test_explicit_recheck_detects_drift_without_overwriting(self):
        path=next((settings.BASE_DIR/'outputs').glob('*/01_基础档案_模拟.xlsx'))
        with tempfile.TemporaryDirectory() as temp,self.settings(BASE_DIR=Path(temp)):
            batch,_=stage_file(path);commit_batch(batch.pk)
            record=Record.objects.get(dataset='departments',business_key='D04');record.values={**record.values,'owner':'已批准的其他值'};record.record_hash=fingerprint(record.values);record.revision+=1;record.save()
            replay,repeated=stage_file(path);self.assertTrue(repeated);self.assertEqual(replay.pk,batch.pk)
            self.client.force_login(self.quality);self.assertEqual(self.post(f'/api/imports/{batch.pk}/recheck',{}).status_code,403)
            self.client.force_login(self.admin);r=self.post(f'/api/imports/{batch.pk}/recheck',{});self.assertEqual(r.status_code,200,r.content)
            new=ImportBatch.objects.get(pk=r.json()['id']);self.assertNotEqual(new.pk,batch.pk)
            row=new.rows.get(dataset='departments',business_key='D04');self.assertEqual(row.status,'conflict')
            record.refresh_from_db();self.assertEqual(record.values['owner'],'已批准的其他值')
