from copy import deepcopy
from datetime import datetime, timedelta
from unittest.mock import patch
from django.test import SimpleTestCase, TestCase
from django.contrib.auth.models import User, Group
from django.core.exceptions import ValidationError
from app.analysis_engine import run_analysis
from app.production import audit, resource_days
from app.schema import SCHEMAS
from scripts.production_schedule import CalendarScheduler

CUTOFF='2026-10-01T18:00:00'
def fixture():
    d={k:[] for k in SCHEMAS}
    d['equipment']=[dict(id='EQ',name='模拟设备',process='冲片',workshop='冲压')]
    d['employees']=[dict(id='E',hourly_cents=6000)]
    d['production_resources']=[dict(id='R',equipment_id='EQ',process='冲片',station='工位1',employee_id='E',capacity=1,max_batch_qty=60,effective='2026-09-01')]
    d['resource_calendars']=[dict(id='C1',resource_id='R',employee_id='E',started='2026-09-21T08:00:00',finished='2026-09-21T12:00:00'),dict(id='C2',resource_id='R',employee_id='E',started='2026-09-21T13:00:00',finished='2026-09-21T18:00:00')]
    d['skills']=[dict(id='S',employee_id='E',process='冲片',approved='2026-01-01',expires='2027-01-01',status='有效')]
    d['operations']=[dict(id='OP',resource_id='R',equipment_id='EQ',employee_id='E',work_order_id='WO',object_id='B',process='冲片',started='2026-09-21T08:00:00',finished='2026-09-21T09:00:00',input_qty=20)]
    d['labor_entries']=[dict(id='L',operation_id='OP',employee_id='E',work_order_id='WO',activity='生产',started='2026-09-21T08:00:00',finished='2026-09-21T09:00:00',minutes=60,hourly_cents=6000,amount_cents=6000)]
    d['costs']=[dict(id='K',category='直接人工',work_order_id='WO',amount_cents=6000)]
    d['attendance']=[dict(id='A',employee_id='E',date='2026-09-21',productive_hours=1,setup_hours=0,rework_hours=0,wait_hours=8,support_hours=0,scheduled_hours=9)]
    return d

class ResourceTests(SimpleTestCase):
    def setUp(self):self.d=fixture()
    def test_lunch_and_downtime_are_not_available_slots(self):
        scheduler=CalendarScheduler(self.d['production_resources'],self.d['resource_calendars'],{'EQ':[(datetime(2026,9,21,13),datetime(2026,9,21,14))]})
        _,start,end=scheduler.reserve('冲片',datetime(2026,9,21,11,45),30,20)
        self.assertEqual((start.hour,start.minute,end.hour,end.minute),(14,0,14,30))
        with self.assertRaises(ValueError):scheduler.reserve('冲片',datetime(2026,9,21,8),20,61)
    def test_duplicate_calendars_and_overlapping_stops_are_unioned(self):
        self.d['resource_calendars'].append(deepcopy(self.d['resource_calendars'][0]))
        self.d['downtime']=[dict(id='D1',equipment_id='EQ',started='2026-09-21T11:00:00',finished='2026-09-21T13:30:00'),dict(id='D2',equipment_id='EQ',started='2026-09-21T13:00:00',finished='2026-09-21T14:00:00')]
        r=resource_days(self.d,CUTOFF)[0]
        self.assertEqual((r['scheduled_minutes'],r['blocked_minutes'],r['available_minutes']),(540,120,420))
        self.assertAlmostEqual(r['occupancy_pct'],60/420*100,places=3)
    def test_overlap_and_zero_availability_are_unknown_not_clamped(self):
        self.d['operations'].append({**self.d['operations'][0],'id':'OP2'})
        self.assertIsNone(resource_days(self.d,CUTOFF)[0]['occupancy_pct'])
        self.assertIn('resource_id_overlap',audit(self.d,CUTOFF)['findings'])
        self.d['operations']=[]
        self.d['maintenance']=[dict(id='M',equipment_id='EQ',started='2026-09-20T08:00:00',finished=None)]
        row=resource_days(self.d,CUTOFF)[0]
        self.assertEqual(row['available_minutes'],0);self.assertIsNone(row['occupancy_pct'])
    def test_cross_midnight_work_splits_to_each_resource_day(self):
        self.d['resource_calendars']=[dict(id='C',resource_id='R',started='2026-09-21T23:00:00',finished='2026-09-22T01:00:00')]
        self.d['operations'][0].update(started='2026-09-21T23:30:00',finished='2026-09-22T00:30:00')
        rows=resource_days(self.d,CUTOFF)
        self.assertEqual([(r['date'],r['busy_minutes'],r['scheduled_minutes']) for r in rows],[('2026-09-21',30,60),('2026-09-22',30,60)])
    def test_calendar_skill_labor_and_cost_failures_are_detected(self):
        self.assertTrue(audit(self.d,CUTOFF)['passed'])
        self.d['skills'][0]['expires']='2026-09-20'
        self.d['labor_entries'][0]['minutes']=30
        self.d['costs'][0]['amount_cents']=5999
        self.d['attendance'][0]['productive_hours']=2
        issues=audit(self.d,CUTOFF)['findings']
        for key in ['missing_skill','labor_assignment','labor_cost','direct_labor_not_reconciled','attendance_balance']:
            self.assertIn(key,issues)
    def test_work_during_a_repair_is_invalid(self):
        self.d['maintenance']=[dict(id='M',equipment_id='EQ',started='2026-09-21T08:30:00',finished=None)]
        self.assertIn('during_equipment_block',audit(self.d,CUTOFF)['findings'])
    def test_conflicts_block_aggregated_occupancy_ratio(self):
        self.d['operations'].append({**self.d['operations'][0],'id':'OP2'})
        rows=resource_days(self.d,CUTOFF);user=type('Admin',(),{'is_authenticated':True,'is_active':True,'is_superuser':True})()
        with patch('app.analysis_engine.semantic.rows',return_value=rows):
            with self.assertRaises(ValidationError):run_analysis(user,'bi_resource_day',{'dimension':'process','metrics':[{'agg':'ratio','field':'busy_minutes','denominator':'available_minutes'}]})

class ResourcePermissionTests(TestCase):
    def test_board_labor_splits_cross_day_and_preserves_cents(self):
        d=fixture();d['operations'][0].update(started='2026-09-21T23:30:00',finished='2026-09-22T00:30:00')
        d['labor_entries'][0].update(started='2026-09-21T23:30:00',finished='2026-09-22T00:30:00',amount_cents=101)
        d['resource_calendars']=[dict(id='C',resource_id='R',started='2026-09-21T23:00:00',finished='2026-09-22T01:00:00')]
        u=User.objects.create_user('admin',password='test',is_superuser=True);self.client.force_login(u);totals=[]
        with patch('app.analytics.tables',return_value=d),patch('app.semantic.rows',return_value=resource_days(d,CUTOFF)):
            for day in ['2026-09-21','2026-09-22']:
                body=self.client.get('/api/production',{'date':day,'process':'冲片'}).json();totals.append(body['labor'][0])
        self.assertEqual([x['hours'] for x in totals],[.5,.5]);self.assertEqual(sum(x['amount_cents'] for x in totals),101)
    def test_board_hides_labor_and_rates_by_role(self):
        d=fixture();facts=resource_days(d,CUTOFF)
        for role,expect_labor,expect_cost in [('viewer',False,False),('operations',True,False),('admin',True,True)]:
            u=User.objects.create_user(role,password='test');u.groups.add(Group.objects.get_or_create(name=role)[0]);self.client.force_login(u)
            with patch('app.analytics.tables',return_value=d),patch('app.semantic.rows',return_value=facts):
                response=self.client.get('/api/production',{'date':'2026-09-21','process':'冲片'})
                self.assertEqual(response.status_code,200);body=response.json()
                self.assertEqual(body['labor'] is not None,expect_labor)
                if expect_labor:self.assertEqual('amount_cents' in body['labor'][0],expect_cost)
                bad=self.client.get('/api/production',{'date':'2020-01-01','process':'冲片'});self.assertEqual(bad.status_code,400)
