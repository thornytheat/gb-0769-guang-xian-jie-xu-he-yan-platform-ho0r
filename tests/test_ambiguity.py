import copy
import hashlib
import json
from itertools import combinations

from app.modules.certificate.service import certify
from app.modules.pairs.ambiguity import avoid_score, optimal_context, rigid
from app.pipeline import run


def tied(dirty, loss):
    material = copy.deepcopy(dirty)
    material['traces']['b'] += f'B-000,943,m,{loss}\n'
    return material


def test_tie_flipping_verdict_holds_joint(dirty):
    out = run(tied(dirty, '0.51'))
    assert out['pairs']['ambiguous'] is True
    first = out['pairs']['pairs'][0]
    assert (first['rigid'], first['alt_b']) == (False, ['B-01'])
    single = next(s for s in out['pairs']['singles'] if s['id'] == 'B-01')
    assert single['possible_partner'] == ['A-01']
    design = out['design']
    assert (design['contested'], design['signable']) == (1, 2)
    row = design['rows'][0]
    assert (row['joint'], row['stability'], row['decision']) == ('F-01', 'CONTESTED', 'HOLD_RETEST')
    assert row['alternatives'] == [{'a': 'A-01', 'b': 'B-01', 'net_db': '0.1000', 'code': 'PASS'}]
    decisions = {r['joint']: r['decision'] for r in design['rows']}
    assert [j for j, d in decisions.items() if d == 'SIGN_NOW'] == ['F-02', 'F-04']


def test_tie_keeping_verdict_signs_joint(dirty):
    design = run(tied(dirty, '0.29'))['design']
    assert (design['contested'], design['signable']) == (0, 3)
    row = design['rows'][0]
    assert (row['joint'], row['code'], row['stability'], row['decision']) == ('F-01', 'PASS', 'STABLE', 'SIGN_NOW')


def test_evidence_can_vanish_holds_joint():
    traces = {'a': 'event,distance,unit,loss_db\nA1,50,m,0.10\nA2,50,m,0.10\nA3,250,m,0.10\n',
              'b': 'event,distance,unit,loss_db\nB1,850,m,0.10\n',
              'design': 'joint,distance,unit,limit_db\nJ1,100,m,0.2\n'}
    settings = {'length_m':'1000','zero_a_m':'0','zero_b_m':'0','pair_tol_m':'100','design_tol_m':'60','reference_limit_db':'0.2'}
    design = run({'traces': traces, 'settings': settings})['design']
    row = design['rows'][0]
    assert (row['code'], row['stability'], row['decision']) == ('PASS', 'CONTESTED', 'HOLD_RETEST')
    assert design['contested'] == 1


def test_sibling_joints_without_tie_stay_settled(clean):
    clean['traces']['design'] += 'C-X,101,m,0.2\n'
    design = run(clean)['design']
    rows = {r['joint']: r for r in design['rows']}
    assert rows['C-1']['decision'] == 'SIGN_NOW'
    assert (rows['C-X']['stability'], rows['C-X']['decision']) == ('STABLE', None)
    assert design['contested'] == 0


def test_certificate_names_signable_and_held_joints(client, dirty):
    run_id = client.post('/api/inspections', json=tied(dirty, '0.51')).json['inspection_id']
    cert = client.get('/api/certificate/' + run_id).json
    assert cert['approved'] is False
    assert cert['blockers'] == ['MISSING_JOINTS', 'LOSS_OVER_LIMIT', 'CONTESTED_JOINTS']
    assert cert['sign_now'] == ['F-02', 'F-04']
    assert cert['hold_retest'] == ['F-01']


def test_reconciliation_and_download_share_one_evidence_batch(client, dirty):
    material = tied(dirty, '0.51')
    preview = client.post('/api/design', json=material).json
    run_id = client.post('/api/inspections', json=material).json['inspection_id']
    cert = client.get('/api/certificate/' + run_id).json
    assert client.get('/api/export/' + run_id).json == cert
    assert cert['record']['computed']['design']['rows'] == preview['rows']
    decisions = {row['joint']: row['decision'] for row in preview['rows']}
    assert cert['sign_now'] == [j for j, d in decisions.items() if d == 'SIGN_NOW']
    assert cert['hold_retest'] == [j for j, d in decisions.items() if d == 'HOLD_RETEST']
    raw = json.dumps(cert['record'], sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    assert hashlib.sha256(raw).hexdigest() == cert['integrity_sha256']


def test_remeasurement_keeps_original_certificate_verifiable(client, dirty):
    material = tied(dirty, '0.51')
    first = client.post('/api/inspections', json=material)
    run_id = first.json['inspection_id']
    cert_before = client.get('/api/certificate/' + run_id).json
    assert cert_before['hold_retest'] == ['F-01']
    supplementary = client.post('/api/inspections', json=dirty)
    assert supplementary.status_code == 201 and supplementary.json['inspection_id'] != run_id
    cert_after = client.get('/api/certificate/' + run_id).json
    assert cert_after == cert_before
    raw = json.dumps(cert_after['record'], sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    assert hashlib.sha256(raw).hexdigest() == cert_after['integrity_sha256']
    rerun = client.post('/api/inspections', json=material)
    assert (rerun.status_code, rerun.json['created']) == (200, False)
    assert rerun.json['record'] == cert_before['record']
    assert len(client.get('/api/inspections').json['inspections']) == 2


def test_legacy_record_without_stability_still_certifies():
    record = {'inspection_id': 'legacy', 'computed': {
        'design': {'missing': 0, 'over_limit': 0, 'design_count': 1, 'rows': [{'joint': 'J1'}]},
        'trace': {'isolated': []}}}
    result = certify(record)
    assert (result['approved'], result['sign_now'], result['hold_retest']) == (True, [], [])


def brute_force(left, right, gap, forbidden=frozenset()):
    best, matchings = (0, 0), []
    for count in range(min(len(left), len(right)) + 1):
        for ix in combinations(range(len(left)), count):
            for iy in combinations(range(len(right)), count):
                matched = set(zip(ix, iy))
                spans = [abs(left[x] - right[y]) for x, y in matched]
                if not matched & forbidden and max(spans, default=0) <= gap:
                    score = (count, -sum(spans))
                    if score > best:
                        best, matchings = score, []
                    if score == best:
                        matchings.append(matched)
    return best, matchings


CASES = [([0, 50, 250], [150], 100), ([100], [97, 101], 4), ([0, 5, 7], [0, 2, 6, 8], 3),
         ([10, 20, 30], [12, 18, 29], 2), ([1, 2], [1, 2], 1), ([], [1], 2), ([5], [], 2),
         ([0, 10, 20, 30], [2, 9, 21, 28], 3), ([100, 105], [97, 101], 4)]


def test_optimal_context_matches_brute_force_tie_class():
    for left, right, gap in CASES:
        best, matchings = brute_force(left, right, gap)
        ctx = optimal_context(left, right, gap)
        assert ctx['score'] == best
        for i in range(len(left)):
            assert ctx['partners_a'][i] == sorted({y for m in matchings for x, y in m if x == i})
            assert ctx['a_can_be_single'][i] == any(all(x != i for x, _ in m) for m in matchings)
        for j in range(len(right)):
            assert ctx['partners_b'][j] == sorted({x for m in matchings for x, y in m if y == j})
            assert ctx['b_can_be_single'][j] == any(all(y != j for _, y in m) for m in matchings)
        for i in range(len(left)):
            for j in range(len(right)):
                expected = any((i, j) in m for m in matchings) and all((i, j) in m for m in matchings)
                assert rigid(ctx, i, j) == expected


def test_avoid_score_matches_brute_force():
    for left, right, gap in CASES:
        ctx = optimal_context(left, right, gap)
        possible = [(i, j) for i in range(len(left)) for j in ctx['partners_a'][i]]
        for forbidden in (set(), set(possible[:1]), set(possible)):
            best, _ = brute_force(left, right, gap, forbidden)
            assert avoid_score(ctx, forbidden) == best
