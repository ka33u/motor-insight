from copy import deepcopy
import csv, hashlib, io, json
from unittest.mock import patch
from django.http import QueryDict
from django.test import SimpleTestCase
from django.contrib.auth.models import User, Group
from app import analytics, supply, wip_readiness as eng
from app.models import Record, AuditEvent
from .test_platform import PlatformCase
from .test_material_planning import fixture as materials, issue
from .test_wip_flow import fixture as wip, event, lot


def fixture():
    d=materials();v=wip()
    for ds in ('wip_locations','wip_lots','wip_openings','wip_event_versions','wip_event_lines','batches','employees'):d[ds]=deepcopy(v[ds])
    for r in d['batches']:r['work_order_id']=r['work_order_id'].replace('WO','W')
    for r in d['wip_lots']:r['product_id']='P1'
    d['products'][0]['route_version']='R1'
    d['routes']=[dict(id='RT1',product_id='P1',process='冲片',version='R1',branch='定子'),dict(id='RT2',product_id='P1',process='冲片',version='R1',branch='转子')]
    d['operations']=[dict(id='BG1',work_order_id='W1',object_type='生产批次',object_id='R1',process='冲片',equipment_id='EQ1',resource_id='RS1',employee_id='E01',started='2026-09-01T08:00:00',finished='2026-09-01T09:00:00',input_qty=10,good_qty=10,scrap_qty=0,rework_qty=0,status='完成')]
    d['inventory_movements']=[issue()]
    return d


class WipReadinessRules(SimpleTestCase):
    def calc(self,d=None):return eng.WipReadiness(fixture() if d is None else d)
    def test_three_grains_are_distinct_and_no_schedule_fabricated(self):
        d=self.calc();r=d.details['W1'];self.assertEqual(r['row']['reported'],1)
        self.assertEqual(r['row']['wip_groups'][0]['wip_qty'],10)
        m=r['materials'][0];self.assertEqual((m['gross_required'],m['issued_qty'],m['remaining_required']),(4,2,2))
        for k in ('remaining_task_qty','remaining_task_minutes','remaining_material_qty'):self.assertIsNone(r['row'][k])
        self.assertEqual(r['row']['scheduling_state'],'not_computed');self.assertEqual(len(r['gaps']),4)
    def test_same_name_routes_never_auto_bind_even_one_candidate(self):
        value=fixture();d=self.calc(value);r=d.details['W1']['operations'][0]
        self.assertEqual(len(r['route_candidates']),2);self.assertIsNone(r['route_id'])
        value['routes'].pop();self.assertIsNone(self.calc(value).details['W1']['operations'][0]['route_id'])
    def test_future_finish_is_open_future_start_excluded_and_bad_time_unknown(self):
        value=fixture();r=value['operations'][0]
        value['operations'] += [dict(r,id='BG2',finished='2026-10-02T08:00:00'),dict(r,id='BG3',started='2026-10-02T08:00:00',finished=None),dict(r,id='BG4',started='bad')]
        row=self.calc(value).details['W1']['row'];self.assertEqual((row['ended_reports'],row['open_reports'],row['future_reports'],row['unknown_reports']),(1,1,1,1))
        self.assertEqual(row['reported'],2)
    def test_time_direction_timezone_and_empty_finish(self):
        base=fixture()['operations'][0];end=eng.wip_flow.clock(analytics.AS_OF)
        for r,state in [(dict(base,finished=None),'open'),(dict(base,finished=''),'open'),(dict(base,finished=base['started']),'ended'),(dict(base,finished='2026-08-01T08:00:00'),'unknown'),(dict(base,started=base['started']+'Z'),'unknown')]:self.assertEqual(eng.operation_state(r,end),state)
    def test_missing_baseline_unknown_not_zero_and_no_roots_not_complete(self):
        value=fixture();value['wip_openings']=[];d=self.calc(value)
        for r in d.rows:
            self.assertTrue(r['position_unknown']);self.assertTrue(all(g['wip_qty'] is None for g in r['wip_groups']))
        self.assertFalse(d.details['W1']['positions'])
    def test_tainted_part_keeps_known_subtotal_but_null_complete_quantity(self):
        value=fixture();value['batches'][1]['work_order_id']='W1';value['wip_openings'].pop()
        g=self.calc(value).details['W1']['row']['wip_groups'][0]
        self.assertEqual((g['roots'],g['verified_roots'],g['known_wip_qty'],g['unknown_roots']),(2,1,10,1));self.assertIsNone(g['wip_qty'])
    def test_isolated_positions_are_not_usable_stock(self):
        value=fixture();value['wip_openings'][0]['location_id']='ISO';r=self.calc(value).details['W1']
        self.assertEqual(r['positions'][0]['location_kind'],'隔离区');self.assertEqual(r['row']['wip_groups'][0]['wip_qty'],10)
        self.assertIsNone(r['row']['remaining_material_qty'])
    def test_closed_order_with_wip_exposes_conflict_not_zero_material(self):
        value=fixture();value['work_orders'][0]['status']='完工待清尾';r=self.calc(value).details['W1']
        self.assertIn('closed_wip',r['row']['flags']);self.assertTrue(r['row']['material_uncomputed']);self.assertFalse(r['materials']);self.assertTrue(any('未计算' in s for s in r['material_issues']))
    def test_assembly_and_reports_do_not_credit_remaining_material(self):
        value=fixture();value['operations'] += [dict(value['operations'][0],id='BG2')];value['units']=[dict(id='SN1',work_order_id='W1',product_id='P1',assembly_at='2026-09-20T08:00:00')]
        r=self.calc(value).details['W1'];self.assertEqual(r['row']['assembled_sn'],1);self.assertEqual(r['row']['reported'],2);self.assertEqual(r['materials'][0]['remaining_required'],2)
    def test_future_and_mismatched_sn_not_counted_as_assembled(self):
        value=fixture();value['units']=[dict(id=k,work_order_id='W1',product_id=p,assembly_at=t) for k,p,t in [('S1','P1','2026-10-02T08:00:00'),('S2','P2','2026-09-20T08:00:00'),('S3','P1','bad')]]
        r=self.calc(value).details['W1']['row'];self.assertEqual((r['assembled_sn'],r['unknown_sn']),(0,2))
    def test_stock_and_operations_source_complete_without_money(self):
        r=self.calc().details['W1'];refs={(s['dataset'],s['key']) for s in r['sources']}
        self.assertTrue({('inventory_opening','O1'),('inventory_movements','I1'),('operations','BG1'),('routes','RT1'),('wip_openings','O1'),('employees','E01'),('production_resources','RS1')}<=refs)
        self.assertNotIn('price_cents',json.dumps(r));self.assertNotIn('12345',json.dumps(r))
    def test_cross_order_mixed_lot_retains_root_shares_without_double_counting(self):
        value=fixture();lot(value,'L3');value['wip_lots'][-1]['product_id']='P1'
        event(value,'MIX','合批',[('L1','A','R1',10),('L2','A','R2',10)],[('L3','A','R1',10),('L3','A','R2',10)])
        d=self.calc(value)
        for key in ('W1','W2'):
            r=d.details[key];self.assertEqual(r['row']['wip_groups'][0]['wip_qty'],10)
            self.assertEqual((r['positions'][0]['qty'],r['positions'][0]['whole_lot_qty']),(10,20))
            self.assertTrue({('wip_openings','O1'),('wip_openings','O2'),('batches','R1'),('batches','R2')}<={(s['dataset'],s['key']) for s in r['sources']})
    def test_filters_match_exact_scope_and_stage_does_not_change_topline(self):
        d=self.calc();f=eng.filters({'stage':'reported'});self.assertEqual(len(d.cohort(f)),3);self.assertEqual(len(d.selected(f)),1)
        self.assertEqual(len(d.selected(eng.filters({'work_order_id':'W'}))),0);self.assertEqual(len(d.selected(eng.filters({'q':'w1'}))),1)
        for q in ({'stage':'bad'},{'q':'x'*151},{'salary':'yes'},QueryDict('q=W1&q=W2')):
            with self.assertRaises(ValueError):eng.filters(q)
    def test_empty_and_pure_no_input_mutation(self):
        value=fixture();before=deepcopy(value);self.calc(value);self.assertEqual(value,before)
        d=self.calc({});self.assertEqual(d.summary([])['work_orders'],0);self.assertFalse(d.matrix([]))


class WipReadinessAPI(PlatformCase):
    def setUp(self):
        super().setUp()
        for ds,rows in fixture().items():
            for r in rows:self.record(ds,r)
        for cache in (eng.cached,analytics._tables,supply.cached):cache.cache_clear();self.addCleanup(cache.cache_clear)
        self.client.force_login(self.admin)
    def board(self,q=''):
        r=self.client.get('/api/wip-readiness'+q);self.assertEqual(r.status_code,200,r.content);return r.json()
    def test_board_detail_sources_and_full_export(self):
        b=self.board('?stage=reported');q='?stage=reported&receipt='+b['receipt'];self.assertEqual((b['summary']['work_orders'],b['total']),(3,1))
        d=self.client.get('/api/wip-readiness/rows/W1'+q);self.assertEqual(d.status_code,200);self.assertEqual(d['Cache-Control'],'no-store')
        sources=self.client.get('/api/wip-readiness/rows/W1/evidence'+q).json()['rows'];raw=Record.objects.get(dataset='operations',business_key='BG1').source_row
        self.assertTrue(any(r['key']=='BG1' and r['row']==raw.row_number and r['sheet']==raw.sheet for r in sources))
        before=list(Record.objects.values());r=self.client.get('/api/wip-readiness/export'+q+'&page=99');self.assertEqual(r.status_code,200)
        text=r.content.decode('utf-8-sig');self.assertIn('BG1',text);self.assertIn('定子',text);self.assertIn('剩余工序排程',eng.BOUNDARY)
        e=AuditEvent.objects.latest('id');self.assertEqual(e.detail['work_orders'],1);self.assertEqual(e.detail['file_sha256'],hashlib.sha256(r.content).hexdigest());self.assertEqual(list(Record.objects.values()),before)
    def test_outside_scope_and_empty_export(self):
        b=self.board('?work_order_id=W2');q='?work_order_id=W2&receipt='+b['receipt'];self.assertEqual(self.client.get('/api/wip-readiness/rows/W1'+q).status_code,404)
        b=self.board('?stage=closed_wip');self.assertEqual(b['total'],0);self.assertEqual(self.client.get('/api/wip-readiness/export?stage=closed_wip&receipt='+b['receipt']).status_code,200)
    def test_six_roles_and_no_raw_payroll_or_cost(self):
        for role in ('admin','analyst','operations','quality','finance','viewer'):
            u=User.objects.create_user('wr_'+role);u.groups.add(Group.objects.get_or_create(name=role)[0]);self.client.force_login(u);b=self.board();q='?receipt='+b['receipt']
            for path in ('/api/wip-readiness/rows/W1','/api/wip-readiness/rows/W1/evidence','/api/wip-readiness/export'):
                r=self.client.get(path+q);self.assertEqual(r.status_code,200,r.content);self.assertNotIn('cents',r.content.decode());self.assertNotIn('12345',r.content.decode())
        self.client.logout();self.assertEqual(self.client.get('/api/wip-readiness').status_code,401)
    def test_receipt_enforces_scope_revision_and_definition(self):
        self.assertEqual(self.client.get('/api/wip-readiness/export').status_code,400);b=self.board();q='?receipt='+b['receipt']
        self.assertEqual(self.client.get('/api/wip-readiness/export'+q+'&q=W1').status_code,409)
        with patch('app.wip_readiness.rule_hash',return_value='new'):
            self.assertEqual(self.client.get('/api/wip-readiness/export'+q).status_code,409)
        r=Record.objects.get(dataset='operations',business_key='BG1');r.revision+=1;r.save();self.assertEqual(self.client.get('/api/wip-readiness/export'+q).status_code,409)
    def test_pagination_duplicates_and_mutation_are_rejected(self):
        for suffix in ('?page=0','?page=-1','?page=100001','?q=W1&q=W2','?stage=no'):
            self.assertEqual(self.client.get('/api/wip-readiness'+suffix).status_code,400)
        self.assertEqual(self.client.post('/api/wip-readiness').status_code,405)
    def test_audit_failure_does_not_return_export(self):
        b=self.board();before=AuditEvent.objects.count()
        with patch('app.wip_readiness_views.AuditEvent.objects.create',side_effect=ValueError('unavailable')):
            self.assertEqual(self.client.get('/api/wip-readiness/export?receipt='+b['receipt']).status_code,400)
        self.assertEqual(AuditEvent.objects.count(),before)
