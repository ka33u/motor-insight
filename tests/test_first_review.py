from copy import deepcopy
from django.test import SimpleTestCase
from app import analytics, first_piece, first_review
from .test_first_piece import fixture, FirstPieceAPITests

AT = '2026-09-22T12:00:00'


def review(data, **delta):
    result = first_piece.analyze(data, AT)
    row = dict(id='SJ-FH-0001-V01', plan_id='PQC1', version=1, previous_id=None, status='已登记', basis_at=AT,
               check_id=result['rows'][0]['latest_id'], basis_hash=first_review.basis_hash(result['details']['PQC1'], data, AT),
               rule_hash=first_review.basis_rule(), reviewed='2026-09-22T12:10:00', registered='2026-09-22T12:15:00',
               decision='复核通过', reviewer_id='E1', reference='SIM-SJ-FH-0001', note='合成复核记录')
    row.update(delta)
    return row


class FirstReviewTests(SimpleTestCase):
    def setUp(self):
        self.d = fixture()
        self.d[first_review.DATASET] = [review(self.d)]

    def result(self):
        return first_review.analyze(self.d, first_piece.analyze(self.d, analytics.AS_OF), analytics.AS_OF)

    def row(self):
        return self.result()['rows']['PQC1']

    def version(self, **delta):
        row = dict(self.d[first_review.DATASET][0], id='SJ-FH-0001-V02', previous_id='SJ-FH-0001-V01', version=2, registered='2026-09-23T12:00:00')
        row.update(delta)
        self.d[first_review.DATASET].append(row)

    def test_matched_declared_pass_does_not_change_evidence(self):
        before = deepcopy(self.d)
        self.assertEqual(self.row()['state'], 'matched')
        self.assertEqual(self.d, before)
        self.assertIn('不是电子签名', first_review.NOTICE)

    def test_changed_reading_even_inside_bounds_requires_new_basis(self):
        self.d['process_readings'][0]['value'] = .04
        self.assertEqual(self.row()['state'], 'stale')

    def test_new_check_after_review_requires_recheck(self):
        self.d['process_checks'].append(dict(self.d['process_checks'][0], id='C2', checked='2026-09-23T12:00:00'))
        self.assertEqual(self.row()['state'], 'stale')

    def test_future_check_does_not_invalidate_current_review(self):
        self.d['process_checks'].append(dict(self.d['process_checks'][0], id='C2', checked='2026-10-03T12:00:00'))
        self.assertEqual(self.row()['state'], 'matched')

    def test_wrong_check_never_counts_as_matched(self):
        self.d[first_review.DATASET][0]['check_id'] = 'OTHER'
        self.assertEqual(self.row()['state'], 'invalid')

    def test_pass_declaration_cannot_override_failed_measurement(self):
        self.d['process_readings'][0]['value'] = .06
        self.d[first_review.DATASET] = [review(self.d)]
        self.assertEqual(self.row()['state'], 'contradicted')

    def test_held_and_pending_are_not_approvals(self):
        for decision, state in [('不予通过', 'held'), ('待补充', 'pending')]:
            self.d[first_review.DATASET][0]['decision'] = decision
            self.assertEqual(self.row()['state'], state)

    def test_withdrawal_does_not_fall_back(self):
        self.version(status='撤销')
        self.assertEqual(self.row()['state'], 'withdrawn')
        self.assertEqual(self.row()['selected']['version'], 2)

    def test_draft_and_future_do_not_replace_known_review(self):
        self.version(status='草稿')
        self.assertEqual(self.row()['selected']['version'], 1)
        self.d[first_review.DATASET][-1].update(status='已登记', registered='2026-10-02T12:00:00')
        self.assertEqual(self.row()['selected']['version'], 1)
        self.d[first_review.DATASET] = self.d[first_review.DATASET][1:]
        self.assertEqual(self.row()['state'], 'none')

    def test_discontinuous_or_duplicate_version_does_not_fall_back(self):
        self.version(version=3)
        self.assertEqual(self.row()['state'], 'invalid')
        self.d[first_review.DATASET][-1]['version'] = 1
        self.assertEqual(self.row()['state'], 'invalid')

    def test_chronology_and_rule_change(self):
        self.d[first_review.DATASET][0]['reviewed'] = '2026-09-21T00:00:00'
        self.assertEqual(self.row()['state'], 'invalid')
        self.d[first_review.DATASET] = [review(self.d, rule_hash='0'*64)]
        self.assertEqual(self.row()['state'], 'stale')

    def test_missing_plan_or_patrol_remains_unmatched(self):
        self.d['process_check_plans'][0]['stage'] = '巡检'
        r = self.result()
        self.assertEqual(len(r['unmatched']), 1)
        self.assertEqual(sum(r['summary'].values()), 0)

    def test_import_row_validation(self):
        self.assertEqual(first_review.issues(review(self.d)), [])
        for delta in [dict(version=0), dict(basis_hash='bad'), dict(status='通过'), dict(previous_id='X'), dict(registered='2026-09-20T00:00:00'), dict(check_id=None), dict(note='')]:
            self.assertTrue(first_review.issues(review(self.d, **delta)), delta)

    def test_price_change_is_not_review_basis_change(self):
        self.d['products'][0]['price_cents'] = 12345
        self.d['employees'][0]['hourly_cents'] = 67890
        self.assertEqual(self.row()['state'], 'matched')


class FirstReviewAPITests(FirstPieceAPITests):
    def setUp(self):
        super().setUp()
        self.record(first_review.DATASET, review(fixture()))

    def test_register_summary_filter_detail_and_source(self):
        d = self.board(review='matched').json()
        self.assertEqual((d['total'], d['review_summary']['matched']), (1, 1))
        self.assertEqual(d['review_matrix']['ready']['matched'], 1)
        self.assertEqual(sum(sum(v.values()) for v in d['review_matrix'].values()), d['total'])
        detail = self.client.get('/api/first-piece/PQC1', dict(review='matched', receipt=d['receipt'])).json()
        self.assertEqual(detail['review']['selected']['id'], 'SJ-FH-0001-V01')
        self.assertTrue(any(s['dataset'] == first_review.DATASET for s in detail['sources']))
        self.assertEqual(self.board(review='withdrawn').json()['total'], 0)
        self.assertEqual(self.board(review='bad').status_code, 400)

    def test_review_change_invalidates_existing_receipt(self):
        d = self.board().json()
        self.change(first_review.DATASET, 'SJ-FH-0001-V01', status='撤销')
        self.assertEqual(self.export(d).status_code, 409)
        self.assertEqual(self.board().json()['review_summary']['withdrawn'], 1)

    def test_export_preserves_history_and_escaping(self):
        self.change(first_review.DATASET, 'SJ-FH-0001-V01', reference='=1+1')
        d = self.board().json()
        doc = self.export(d).json()
        self.assertEqual(len(doc['reviews']['PQC1']['history']), 1)
        csv = self.client.get('/api/first-piece/export', dict(receipt=d['receipt'], format='csv')).content.decode('utf-8-sig')
        self.assertIn("'=1+1", csv)
