import copy,tempfile,zipfile,uuid
from pathlib import Path
from datetime import date
from unittest.mock import patch
from django.test import SimpleTestCase
from tests.test_platform import PlatformCase
from tests.test_data_health import item
from app import data_health as health
from app.manufacturing_rules import issues
from app.ingestion import stage_file,commit_batch,fingerprint
from app.import_review import validate_values,decide,snapshot
from app.models import ImportBatch,ImportRow,ImportDecision,Record
from app.schema import SCHEMAS
from scripts.scenario_calendar import work_order_plan


def work(**extra):return dict(id='W1',product_id='P1',planned_qty=15,planned_start='2026-09-19',planned_end='2026-09-22',priority='普通',status='未开工',bom_version='A',route_version='V1',**extra)
def operation():return dict(id='O1',work_order_id='W1',object_type='生产批次',object_id='B1',process='冲片',equipment_id='EQ1',resource_id='RS1',employee_id='E1',started='2026-09-19T08:00:00',finished='2026-09-19T09:00:00',input_qty=15,good_qty=14,scrap_qty=1,rework_qty=3,status='完成')


class ManufacturingRowRules(SimpleTestCase):
    def codes(self,ds,row):return {r['code'] for r in issues(ds,row)}
    def test_plan_dates_same_day_allowed_future_allowed(self):
        for start,end in [('2026-09-22','2026-09-22'),('2027-01-01','2027-02-01')]:self.assertFalse(issues('work_orders',{**work(),'planned_start':start,'planned_end':end}))
    def test_reversed_dates_detected(self):self.assertEqual(self.codes('work_orders',{**work(),'planned_start':'2026-09-23'}),{'WO_PLAN_ORDER'})
    def test_zero_and_negative_plan_quantity(self):
        for qty in [0,-1]:self.assertIn('WO_PLAN_QTY',self.codes('work_orders',{**work(),'planned_qty':qty}))
    def test_positive_batch_quantity(self):
        for qty in [0,-1]:self.assertIn('BATCH_QTY',self.codes('batches',{'qty':qty}))
        self.assertFalse(issues('batches',{'qty':1}))
    def test_schema_errors_do_not_crash_business_check(self):
        for value in [None,False,[],{},'bad',42]:
            self.assertFalse(issues('work_orders',{'planned_start':value,'planned_end':'2026-09-22','planned_qty':False}))
            self.assertFalse(issues('operations',{'started':value,'finished':value,'input_qty':value,'status':'other'}))
    def test_complete_with_scrap_and_rework_subset(self):self.assertFalse(issues('operations',operation()))
    def test_rework_is_not_added_to_output(self):
        row={**operation(),'good_qty':15,'scrap_qty':0,'rework_qty':15};self.assertFalse(issues('operations',row))
    def test_output_over_input_and_incomplete_completed_balance(self):
        for qty in [13,16]:self.assertIn('OP_OUTPUT_QTY',self.codes('operations',{**operation(),'good_qty':qty}))
    def test_running_partial_output(self):self.assertFalse(issues('operations',{**operation(),'status':'进行中','finished':None,'good_qty':3,'scrap_qty':0}))
    def test_running_output_cannot_exceed_input(self):self.assertIn('OP_OUTPUT_QTY',self.codes('operations',{**operation(),'status':'进行中','finished':None,'good_qty':16}))
    def test_rework_cannot_exceed_input(self):self.assertIn('OP_REWORK_SUBSET',self.codes('operations',{**operation(),'rework_qty':16}))
    def test_finish_required_for_completion(self):
        for val in [None,'']:self.assertIn('OP_FINISH_REQUIRED',self.codes('operations',{**operation(),'finished':val}))
    def test_running_cannot_claim_finished(self):self.assertIn('OP_RUNNING_FINISHED',self.codes('operations',{**operation(),'status':'进行中'}))
    def test_positive_duration(self):
        for val in ['2026-09-19T07:00:00','2026-09-19T08:00:00']:self.assertIn('OP_TIME_ORDER',self.codes('operations',{**operation(),'finished':val}))
    def test_positive_input(self):self.assertIn('OP_INPUT_QTY',self.codes('operations',{**operation(),'input_qty':0}))
    def test_negative_output_quantities(self):
        for key in ['good_qty','scrap_qty','rework_qty']:self.assertIn('OP_NONNEGATIVE_QTY',self.codes('operations',{**operation(),key:-1}))
    def test_no_unrelated_dataset_inference(self):self.assertFalse(issues('quotes',{'qty':0,'planned_start':'2026-09-23','planned_end':'2026-09-22'}))
    def test_generator_preserves_normal_window_and_deadline(self):
        self.assertEqual(work_order_plan(date(2026,9,21),date(2026,9,25)),(date(2026,9,18),date(2026,9,24)))
        self.assertEqual(work_order_plan(date(2026,9,26),date(2026,9,23)),(date(2026,9,19),date(2026,9,22)))
    def test_scan_records_rule_identity_without_mutating_facts(self):
        row={**work(),'planned_start':'2026-09-23'};original=copy.deepcopy(row)
        result=health.inspect([item('work_orders',row)],{('products','P1'),('work_orders','W1')},{})
        self.assertEqual(row,original);self.assertEqual(len(result['issues']),1)
        self.assertEqual(result['issues'][0]['rule'],'manufacturing');self.assertIn('WO_PLAN_ORDER',result['issues'][0]['message'])


class ManufacturingImportRules(PlatformCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.admin)
        self.record('products',{'id':'P1'})
    def stage(self,rows):
        class Sheet:
            title='生产工单'
            max_column=len(SCHEMAS['work_orders']['fields'])
            def iter_rows(self,values_only=True,min_row=1,max_row=None):
                values=[[f['label'] for f in SCHEMAS['work_orders']['fields']]]+[[r.get(f['name']) for f in SCHEMAS['work_orders']['fields']] for r in rows]
                return iter(values[min_row-1:max_row])
        class Book:
            sheetnames=['生产工单']
            def __iter__(self):return iter([Sheet()])
            def close(self):pass
        with tempfile.TemporaryDirectory() as temp,self.settings(BASE_DIR=Path(temp)):
            p=Path(temp)/'parser-fixture.xlsx'
            with zipfile.ZipFile(p,'w') as z:z.writestr('fixture.txt','Mocked parser fixture; real XLSX verified in rehearsal.')
            with patch('app.ingestion.load_workbook',return_value=Book()):return stage_file(p)[0]
    def test_preview_rejects_bad_before_duplicate_classification(self):
        bad={**work(),'planned_start':'2026-09-23'};self.record('work_orders',bad)
        batch=self.stage([bad]);row=batch.rows.get();self.assertEqual(row.status,'invalid');self.assertEqual(row.issues[0]['code'],'WO_PLAN_ORDER')
    def test_preview_bad_cannot_satisfy_valid_same_key(self):
        batch=self.stage([{**work(),'planned_start':'2026-09-23'},work()]);self.assertEqual(list(batch.rows.order_by('row_number').values_list('status',flat=True)),['invalid','valid'])
        commit_batch(batch.pk);self.assertEqual(Record.objects.get(dataset='work_orders').values,work())
    def test_preview_corrected_existing_record_remains_conflict(self):
        self.record('work_orders',{**work(),'planned_start':'2026-09-23'});batch=self.stage([work()]);self.assertEqual(batch.rows.get().status,'conflict')
        commit_batch(batch.pk);self.assertEqual(Record.objects.get(dataset='work_orders').values['planned_start'],'2026-09-23')
    def test_submit_rechecks_new_rules_and_cascades_references(self):
        old=self.row('work_orders',{**work(),'planned_start':'2026-09-23'})
        child=self.row('batches',dict(id='B1',work_order_id='W1',kind='定子',qty=15,created='2026-09-19T08:00:00',status='在制',container='箱1'))
        commit_batch(self.batch.pk);old.refresh_from_db();child.refresh_from_db()
        self.assertEqual((old.status,child.status),('invalid','invalid'));self.assertFalse(Record.objects.filter(dataset__in=['work_orders','batches']).exists())
    def test_repair_cannot_reintroduce_bad_dates(self):
        row=self.row('work_orders',work(),'invalid');raw=copy.deepcopy(row.raw)
        response=self.post(f'/api/imports/{self.batch.pk}/rows/{row.pk}/repair',{'expected_row_hash':row.record_hash,'values':{**work(),'planned_start':'2026-09-23'}})
        self.assertEqual(response.status_code,400);row.refresh_from_db();self.assertEqual(row.raw,raw);self.assertEqual(row.normalized,work())
    def proposal(self,value):
        current=self.record('work_orders',work());batch=ImportBatch.objects.create(filename='候选.xlsx',file_hash='candidate',status='staged')
        row=ImportRow.objects.create(batch=batch,sheet='生产工单',row_number=2,dataset='work_orders',business_key='W1',raw=value,normalized=value,record_hash=fingerprint(value),status='conflict')
        payload={'action':'replace','reason':'核验模拟计划日期更正','expected':{k:snapshot(current)[k] for k in ['record_id','revision','hash']}}
        payload['expected']['candidate_hash']=row.record_hash;return current,row,payload
    def test_old_conflict_approval_rechecks_rule(self):
        current,row,p=self.proposal({**work(),'planned_start':'2026-09-23'})
        with self.assertRaisesMessage(ValueError,'计划开工不能晚于计划完工'):decide(row.batch_id,row.pk,'admin',p)
        current.refresh_from_db();self.assertEqual(current.revision,1);self.assertFalse(ImportDecision.objects.exists())
    def test_valid_replacement_keeps_source_and_revision_history(self):
        current,row,p=self.proposal({**work(),'planned_start':'2026-09-18'});decision,repeated=decide(row.batch_id,row.pk,'admin',p)
        self.assertFalse(repeated);self.assertEqual(decision.before['values']['planned_start'],'2026-09-19');self.assertEqual(decision.after['revision'],2)
        current.refresh_from_db();self.assertEqual(current.source_row_id,row.pk)
    def test_keep_legacy_bad_candidate_does_not_require_repair(self):
        current,row,p=self.proposal({**work(),'planned_start':'2026-09-23'});p['action']='keep';decide(row.batch_id,row.pk,'admin',p)
        current.refresh_from_db();self.assertEqual(current.values,work());self.assertEqual(current.revision,1)
    def test_preview_zero_plan_is_invalid(self):self.assertEqual(self.stage([{**work(),'planned_qty':0}]).rows.get().status,'invalid')
    def test_review_validate_operation_numbers(self):
        for ds,key in [('work_orders','W1'),('equipment','EQ1'),('employees','E1'),('production_resources','RS1')]:self.record(ds,{'id':key})
        with self.assertRaisesMessage(ValueError,'返工数'):validate_values('operations',{**operation(),'rework_qty':16})
    def test_historical_scan_retains_its_original_scope_note(self):
        scan=health.run(self.admin,uuid.uuid4());scan.snapshot['note']='旧版仅检查结构字段';scan.snapshot_hash=health.digest(scan.snapshot);scan.engine_hash='older-rules';scan.save()
        board=self.client.get('/api/data-health').json();self.assertTrue(board['stale']);self.assertEqual(board['note'],'旧版仅检查结构字段')
        exported=self.client.get('/api/data-health/export').content.decode('utf-8-sig');self.assertIn('旧版仅检查结构字段',exported)
