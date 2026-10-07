import copy
import json
import time
from unittest.mock import patch
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import Client
from app import object_hub as hub
from app.models import Record, AuditEvent, AccountAccessState, AnalysisModel, Topic, TopicView
from app.schema import SCHEMAS
from app.import_review import ReviewConflict
from tests.test_platform import PlatformCase


class ObjectHubTests(PlatformCase):
    def setUp(self):
        super().setUp(); self.client.force_login(self.admin)
        self.material = self.record('materials', dict(id='000019', name='铜线', spec='0.80 mm', unit='kg', supplier_id='GY00001', unit_cost_cents=90000))
        self.supplier = self.record('suppliers', dict(id='GY00001', name='模拟铜线供应商'))
        self.work_order = self.record('work_orders', dict(id='MO2609-000001', product_id='CP.00001.A', planned_qty=20))
        self.batch_record = self.record('batches', dict(id='DZ2609210001', work_order_id=self.work_order.business_key, container='容器01'))
        self.unit = self.record('units', dict(id='M260921000001', work_order_id=self.work_order.business_key, product_id='CP.00001.A', stator_batch=self.batch_record.business_key, rotor_batch=self.batch_record.business_key, assembly_at='2026-09-21T09:00:00'))

    def body(self, q='', dataset='', mode='contains', page=1, receipt=None):
        return dict(filters=dict(q=q, dataset=dataset, mode=mode), page=page, receipt=receipt)

    def search(self, q='', dataset='', mode='contains', page=1, receipt=None, user=None):
        return hub.search(user or self.admin, self.body(q,dataset,mode,page,receipt))

    def detail(self, record=None, user=None):
        return hub.detail(user or self.admin, (record or self.material).pk)

    def related(self, record, dataset, page=1, receipt=None, user=None):
        user = user or self.admin
        if receipt is None: receipt = self.detail(record,user)['receipt']
        return hub.related(user, record.pk, dict(dataset=dataset,page=page,receipt=receipt))

    def test_empty_search_returns_contracts_without_dumping_all_data(self):
        d = self.search()
        self.assertEqual((d['total'],d['total_all'],d['rows'],d['counts']),(0,0,[],{}))
        self.assertEqual(len(d['types']),14); self.assertIn('不按业务截止',d['time_note'])

    def test_leading_zero_exact_identity_and_same_code_different_tables(self):
        other = self.record('equipment', dict(id='000019',name='绕线机'))
        d = self.search('000019',mode='exact')
        self.assertEqual({r['record_id'] for r in d['rows']},{self.material.pk,other.pk})
        self.assertEqual({r['key'] for r in d['rows']},{'000019'})
        self.assertTrue(all(r['matched']==['编码精确匹配'] for r in d['rows']))
        self.assertEqual(self.search('19',mode='exact')['total'],0)

    def test_contains_names_specs_and_external_order_number_without_identity_guess(self):
        order = self.record('orders',dict(id='SO202609100001',customer_po='PO-EXTERNAL-0001'))
        self.assertEqual(self.search('铜线')['total'],2)
        self.assertEqual(self.search('0.80')['rows'][0]['key'],'000019')
        self.assertEqual(self.search('PO-EXTERNAL-0001')['rows'][0]['record_id'],order.pk)
        self.assertEqual(self.search('PO-EXTERNAL-0001',mode='exact')['total'],0)
        self.assertEqual(self.search('铜线',mode='prefix')['total'],0)

    def test_exact_then_code_prefix_then_name_rank(self):
        for key,name in [('A100','命中'),('A100-B','命中'),('ZZ99','A100描述')]: self.record('equipment',dict(id=key,name=name))
        self.assertEqual([r['key'] for r in self.search('A100')['rows']],['A100','A100-B','ZZ99'])

    def test_exact_is_case_sensitive_prefix_does_not_rewrite_code(self):
        self.record('equipment',dict(id='Case001',name='区分大小写'))
        self.assertEqual(self.search('case001',mode='exact')['total'],0)
        self.assertEqual(self.search('case',mode='prefix')['rows'][0]['key'],'Case001')
        self.assertEqual(self.search('case001')['rows'][0]['matched'],['编码前缀匹配'])

    def test_literal_sql_wildcards_and_quotes_are_not_search_operators(self):
        self.record('equipment',dict(id='ID%_001',name="工具'测试"))
        for q in ('%_','%',"'"):
            self.assertEqual(self.search(q)['total'],1)
        self.assertEqual(self.search("' OR 1=1 --")['total'],0)

    def test_type_filter_keeps_global_facets_and_exact_total(self):
        d = self.search('铜线',dataset='materials')
        self.assertEqual((d['total'],d['total_all']),(1,2))
        self.assertEqual(d['counts'],{'materials':1,'suppliers':1})
        self.assertEqual(d['rows'][0]['dataset'],'materials')

    def test_paging_order_covers_all_records_exactly_once(self):
        for n in range(57):self.record('equipment',dict(id=f'SB-X-{n:04d}',name='分页设备'))
        first = self.search('SB-X-'); second = self.search('SB-X-',page=2,receipt=first['receipt']); third = self.search('SB-X-',page=3,receipt=first['receipt'])
        self.assertEqual([len(x['rows']) for x in (first,second,third)],[25,25,7])
        keys=[r['key'] for d in (first,second,third) for r in d['rows']]
        self.assertEqual(keys,sorted(set(keys))); self.assertEqual(first['total'],57)
        with self.assertRaises(ValidationError):self.search('SB-X-',page=4,receipt=first['receipt'])
        with self.assertRaises(ValidationError):self.search('SB-X-',page=2)

    def test_search_receipt_bound_to_filters_account_and_permission_epoch(self):
        first = self.search('铜')
        for change in [dict(q='线'),dict(q='铜',dataset='materials'),dict(q='铜',mode='prefix')]:
            with self.assertRaises(ReviewConflict):self.search(**change,receipt=first['receipt'])
        with self.assertRaises(ReviewConflict):self.search('铜',receipt=first['receipt'],user=self.quality)
        AccountAccessState.objects.create(user=self.admin,session_epoch=2)
        with self.assertRaises(ReviewConflict):self.search('铜',receipt=first['receipt'])

    def test_new_import_invalidates_paging_and_related_receipts(self):
        search=self.search('铜'); detail=self.detail(self.work_order)
        self.record('units',dict(id='M-NEW',work_order_id=self.work_order.business_key))
        with self.assertRaises(ReviewConflict):self.search('铜',receipt=search['receipt'])
        with self.assertRaises(ReviewConflict):self.related(self.work_order,'units',receipt=detail['receipt'])

    def test_detail_is_full_permitted_record_with_exact_source(self):
        d=self.detail();fields={f['name']:f['value'] for f in d['fields']}
        self.assertEqual(fields['id'],'000019');self.assertEqual(fields['unit_cost_cents'],90000)
        source=d['object']['source'];self.assertEqual((source['sheet'],source['row'],source['batch_id']),('materials',2,str(self.batch.pk)))
        self.assertEqual(source['record_hash'],self.material.record_hash)
        self.assertTrue(d['can_download_excel'])

    def test_money_fields_and_values_hidden_from_search_detail_and_related(self):
        d=self.detail(user=self.quality)
        self.assertNotIn('unit_cost_cents',json.dumps(d));self.assertNotIn('90000',json.dumps(d))
        self.assertFalse(d['can_download_excel'])
        self.assertEqual(self.search('90000',user=self.quality)['total'],0)
        related=self.related(self.supplier,'materials',user=self.quality)
        self.assertNotIn('90000',json.dumps(related));self.assertNotIn('unit_cost_cents',json.dumps(related))

    def test_outgoing_resolves_only_exact_declared_reference(self):
        d=self.detail();supplier=next(r for r in d['outgoing'] if r['field']=='supplier_id')
        self.assertEqual((supplier['state'],supplier['record_id']),('found',self.supplier.pk))
        # The unit's configuration is absent; its work order must not substitute it.
        missing=next(r for r in self.detail(self.unit)['outgoing'] if r['field']=='product_id')
        self.assertEqual((missing['state'],missing['record_id']),('missing',None))

    def test_reference_target_must_match_case_and_complete_key(self):
        self.material.values['supplier_id']='gy00001'
        from app.ingestion import fingerprint
        row=self.material.source_row;row.normalized=self.material.values;row.record_hash=fingerprint(row.normalized);row.save()
        self.material.record_hash=row.record_hash;self.material.save()
        self.assertEqual(self.detail()['outgoing'][0]['state'],'missing')

    def test_one_row_referencing_object_twice_is_counted_once(self):
        d=self.detail(self.batch_record)
        incoming=next(g for g in d['inbound'] if g['dataset']=='units')
        self.assertEqual(incoming['count'],1)
        rows=self.related(self.batch_record,'units',receipt=d['receipt'])['rows']
        self.assertEqual(len(rows),1);self.assertEqual({f['name'] for f in rows[0]['matched_fields']},{'stator_batch','rotor_batch'})

    def test_reverse_references_are_direct_not_transitive_or_name_guessed(self):
        self.record('equipment',dict(id='SB-X',name=self.work_order.business_key))
        d=self.detail(self.work_order);groups={g['dataset']:g['count'] for g in d['inbound']}
        self.assertEqual(groups['units'],1);self.assertEqual(groups['batches'],1);self.assertNotIn('equipment',groups)
        with self.assertRaises(ValidationError):self.related(self.work_order,'equipment')

    def test_related_all_visible_versions_do_not_imply_current_approval(self):
        self.record('units',dict(id='M-FUTURE',work_order_id=self.work_order.business_key,assembly_at='2099-01-01T00:00:00',status='草稿'))
        d=self.related(self.work_order,'units')
        self.assertEqual(d['total'],2);self.assertIn('历史、草稿和未来登记',d['notice'])

    def test_hidden_financial_records_neither_root_nor_inbound_counts(self):
        cost=self.record('costs',dict(id='C-SECRET',work_order_id=self.work_order.business_key,amount_cents=77777))
        self.assertIn('costs',{g['dataset'] for g in self.detail(self.work_order)['inbound']})
        self.assertNotIn('costs',{g['dataset'] for g in self.detail(self.work_order,self.quality)['inbound']})
        with self.assertRaises(Record.DoesNotExist):self.detail(cost,self.quality)
        with self.assertRaises(ValidationError):self.related(self.work_order,'costs',user=self.quality)

    def test_detail_can_follow_visible_non_common_datasets(self):
        cost=self.record('costs',dict(id='C001',work_order_id=self.work_order.business_key,amount_cents=0))
        d=self.detail(cost);self.assertEqual(d['object']['key'],'C001')
        self.assertEqual(next(f['value'] for f in d['fields'] if f['name']=='amount_cents'),0)
        self.assertEqual(d['outgoing'][0]['record_id'],self.work_order.pk)

    def test_restricted_outgoing_does_not_disclose_target_existence(self):
        schema=copy.deepcopy(SCHEMAS['materials']);next(f for f in schema['fields'] if f['name']=='supplier_id')['reference']='skills'
        with patch.dict(SCHEMAS,{'materials':schema}):
            item=self.detail(user=self.quality)['outgoing'][0]
            self.assertEqual(item['state'],'restricted');self.assertNotIn('dataset',item);self.assertIsNone(item['record_id'])

    def test_related_pagination_exact_and_wrong_root_receipt_rejected(self):
        for n in range(28):self.record('units',dict(id=f'MX-{n:04d}',work_order_id=self.work_order.business_key))
        d=self.detail(self.work_order);first=self.related(self.work_order,'units',receipt=d['receipt']);second=self.related(self.work_order,'units',2,d['receipt'])
        self.assertEqual((first['total'],len(first['rows']),len(second['rows'])),(29,25,4))
        self.assertEqual(len({r['record_id'] for r in first['rows']+second['rows']}),29)
        with self.assertRaises(ReviewConflict):self.related(self.batch_record,'units',receipt=d['receipt'])

    def test_schema_and_rule_changes_invalidate_receipts(self):
        d=self.detail(self.work_order)
        with patch('app.object_hub.rules',return_value='changed'):
            with self.assertRaises(ReviewConflict):self.related(self.work_order,'units',receipt=d['receipt'])
        schema=copy.deepcopy(SCHEMAS['units']);schema['fields'][0]['label']='新编号名称'
        with patch.dict(SCHEMAS,{'units':schema}):
            with self.assertRaises(ReviewConflict):self.related(self.work_order,'units',receipt=d['receipt'])

    def test_source_integrity_error_does_not_present_false_lineage(self):
        row=self.material.source_row;row.normalized={'id':'wrong'};row.save()
        with self.assertRaises(ValueError):self.detail()
        with self.assertRaises(ValueError):self.search('000019')

    def test_referenced_target_source_is_checked(self):
        row=self.supplier.source_row;row.record_hash='broken';row.save()
        with self.assertRaises(ValueError):self.detail()

    def test_expiry_tamper_and_operation_mismatch(self):
        now=time.time();d=self.detail(self.work_order);search=self.search('MO')
        with patch('django.core.signing.time.time',return_value=now+hub.AGE+2):
            with self.assertRaises(ReviewConflict):self.related(self.work_order,'units',receipt=d['receipt'])
        with self.assertRaises(ReviewConflict):self.related(self.work_order,'units',receipt=d['receipt']+'x')
        with self.assertRaises(ReviewConflict):self.related(self.work_order,'units',receipt=search['receipt'])

    def test_disabled_and_conflicting_roles_refreshed(self):
        self.admin.is_active=False;self.admin.save()
        with self.assertRaises(PermissionDenied):self.search()
        self.admin.is_active=True;self.admin.save();self.admin.groups.add(self.quality.groups.first())
        with self.assertRaises(PermissionDenied):self.detail()

    def test_unknown_duplicate_and_invalid_input_parameters(self):
        for change in ({'q':True},{'q':'a'*151},{'q':'abc\n'},{'dataset':'costs'},{'dataset':[]},{'mode':[]},{'mode':'sql'},{'extra':1}):
            b=self.body();b['filters'].update(change)
            with self.assertRaises(ValidationError):hub.search(self.admin,b)
        for change in ({'page':True},{'page':0},{'page':1000001},{'page':'1'},{'extra':1}):
            with self.assertRaises(ValidationError):hub.search(self.admin,dict(self.body(),**change))
        for token in (None,True,'x'*1001):
            with self.assertRaises(ValidationError):self.related(self.work_order,'units',receipt=token if token is not None else '')

    def test_http_permission_methods_csrf_and_no_store(self):
        url='/api/object-hub/search';self.assertEqual(self.client.get(url).status_code,405)
        self.assertEqual(self.post(url+'?q=x',self.body('铜')).status_code,400)
        response=self.post(url,self.body('铜'));self.assertEqual(response.status_code,200);self.assertEqual(response['Cache-Control'],'no-store')
        self.assertEqual(self.client.get(f'/api/object-hub/{self.material.pk}?q=x').status_code,400)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin)
        self.assertEqual(secure.post(url,json.dumps(self.body()),content_type='application/json').status_code,403)
        self.client.logout();self.assertEqual(self.post(url,self.body()).status_code,401)

    def test_viewer_search_detail_related_without_business_writes(self):
        viewer=User.objects.create_user('viewer');viewer.groups.add(Group.objects.create(name='viewer'));self.client.force_login(viewer)
        models=[Record,AuditEvent,AnalysisModel,Topic,TopicView];before=[list(m.objects.order_by('pk').values()) for m in models]
        response=self.post('/api/object-hub/search',self.body('MO2609-000001',mode='exact'));self.assertEqual(response.status_code,200)
        record=response.json()['rows'][0]['record_id'];detail=self.client.get(f'/api/object-hub/{record}');self.assertEqual(detail.status_code,200)
        related=self.post(f'/api/object-hub/{record}/related',dict(dataset='units',page=1,receipt=detail.json()['receipt']))
        self.assertEqual(related.status_code,200);self.assertEqual(related.json()['rows'][0]['key'],self.unit.business_key)
        self.assertEqual(before,[list(m.objects.order_by('pk').values()) for m in models])
