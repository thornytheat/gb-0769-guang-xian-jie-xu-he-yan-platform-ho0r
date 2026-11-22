from bisect import bisect_left, bisect_right

from app.modules.loss.verdict import display, verdict
from app.modules.pairs.ambiguity import avoid_score, optimal_context, rigid
from app.modules.pairs.optimal import best_pairs

BUCKETS = {'PASS': 'passed', 'OVER_LIMIT': 'over_limit'}


def bucket_of(code):
    return BUCKETS.get(code, 'missing')


def reconcile(calibrated, joined, loss):
    points, measurements = calibrated['aligned']['design'], loss['rows']
    tolerance = calibrated['settings']['design_tol_mm']
    valid = [row for row in points if not row.get('code')]
    links = best_pairs([r['chain_mm']*2 for r in valid], [r['midpoint_half_mm'] for r in measurements], tolerance*2)
    mapped = {valid[i]['id']: measurements[j] for i,j in links}
    used = {j for _,j in links}
    rows = []
    for point in points:
        pair = mapped.get(point['id'])
        near_singles = [dict(id=r['id'], source=r['source'], line=r['line']) for r in joined['singles']
                        if abs(r['chain_mm']-point['chain_mm']) <= tolerance and not point.get('code')]
        if not pair:
            code = point.get('code') or ('SINGLE_SIDE_ONLY' if near_singles else 'NO_COUPLED_EVIDENCE')
        else:
            code = verdict(pair['net_double_mdb'], point['limit_mdb'])
        rows.append({'joint': point['id'], 'chain_mm': point['chain_mm'], 'design_line': point['line'],
                     'limit_mdb': point['limit_mdb'], 'pair': pair['pair'] if pair else None,
                     'net_db': pair['net_db'] if pair else None, 'code':code,'bucket':bucket_of(code),
                     'near_singles': near_singles,
                     'a_line': pair['a']['line'] if pair else None, 'b_line': pair['b']['line'] if pair else None,
                     'gain_ends': pair['gain_ends'] if pair else []})
    totals = {key: sum(r['bucket'] == key for r in rows) for key in ('passed','over_limit','missing')}
    orphans = [r for i,r in enumerate(measurements) if i not in used]
    measured = len(calibrated['aligned']['a']) + len(calibrated['aligned']['b'])
    result = {'design_count':len(points), **totals, 'balanced':len(points)==sum(totals.values()), 'rows':rows,
              'orphans':orphans, 'orphan_pairs':len(orphans), 'singles': joined['singles'], 'single_count':joined['single_count'],
              'measurements':measured, 'measurements_balanced': measured == 2*(len(mapped)+len(orphans))+joined['single_count']}
    result.update(stabilize(calibrated, points, valid, mapped, rows))
    return result


def stabilize(calibrated, points, valid, mapped, rows):
    """Classify each joint against every equally-good pairing of the traces.

    A joint is STABLE when its bucket is the same under every optimal pairing;
    a stable passed joint may be signed at once (SIGN_NOW).  A joint is
    CONTESTED when another equally-good pairing flips its bucket, so it must
    wait for re-measurement (HOLD_RETEST) instead of being signed on one
    arbitrarily picked evidence set.
    """
    settings = calibrated['settings']
    a_rows, b_rows = calibrated['aligned']['a'], calibrated['aligned']['b']
    left = [r['chain_mm'] for r in a_rows]
    right = [r['chain_mm'] for r in b_rows]
    context = optimal_context(left, right, settings['pair_tol_mm'])
    index_a = {r['id']: k for k, r in enumerate(a_rows)}
    index_b = {r['id']: k for k, r in enumerate(b_rows)}
    tolerance2 = settings['design_tol_mm'] * 2
    chains2 = [p['chain_mm'] * 2 for p in valid]
    candidates = {p['id']: [] for p in valid}
    for i in range(len(left)):
        for j in context['partners_a'][i]:
            midpoint2 = left[i] + right[j]
            for k in range(bisect_left(chains2, midpoint2 - tolerance2),
                           bisect_right(chains2, midpoint2 + tolerance2)):
                candidates[valid[k]['id']].append((i, j))

    def siblings(point, own):
        found = set()
        for i, j in own:
            midpoint2 = left[i] + right[j]
            for k in range(bisect_left(chains2, midpoint2 - tolerance2),
                           bisect_right(chains2, midpoint2 + tolerance2)):
                if valid[k]['id'] != point['id']:
                    found.add(valid[k]['id'])
        return found

    def position_invariant(pool):
        """True when every optimum shows the same midpoints around the joints.

        Holds when each event in the pool is coupled in every optimal pairing
        and all its equally-good partners sit on one chainage, so the design
        alignment sees an unchanging midpoint multiset and cannot reassign.
        """
        for i in {i for i, _ in pool}:
            if context['a_can_be_single'][i] or len({right[k] for k in context['partners_a'][i]}) > 1:
                return False
        for j in {j for _, j in pool}:
            if context['b_can_be_single'][j] or len({left[k] for k in context['partners_b'][j]}) > 1:
                return False
        return True

    contested = signable = 0
    for row, point in zip(rows, points):
        if point.get('code'):
            row.update(stability='STABLE', decision=None, alternatives=[])
            continue
        own = candidates[point['id']]
        primary = mapped.get(point['id'])
        primary_ij = primary and (index_a[primary['a']['id']], index_b[primary['b']['id']])
        buckets, alternatives = set(), []
        for i, j in own:
            net = a_rows[i]['loss_mdb'] + b_rows[j]['loss_mdb']
            code = verdict(net, point['limit_mdb'])
            buckets.add(bucket_of(code))
            if (i, j) != primary_ij:
                alternatives.append({'a': a_rows[i]['id'], 'b': b_rows[j]['id'],
                                     'net_db': display(net), 'code': code})
        if primary is None:
            buckets.add('missing')
        kin = siblings(point, own)
        pool = own + [c for p in valid if p['id'] in kin for c in candidates[p['id']]]
        if position_invariant(pool):
            stability = 'STABLE'
        elif len(buckets) > 1:
            stability = 'CONTESTED'
        elif buckets == {'missing'}:
            stability = 'STABLE'
        elif kin:
            stability = 'CONTESTED'
        elif any(rigid(context, i, j) for i, j in own):
            stability = 'STABLE'
        else:
            stability = 'CONTESTED' if avoid_score(context, set(own)) == context['score'] else 'STABLE'
        alternatives.sort(key=lambda item: (item['a'], item['b']))
        if stability == 'CONTESTED':
            contested += 1
            decision = 'HOLD_RETEST'
        elif row['bucket'] == 'passed':
            signable += 1
            decision = 'SIGN_NOW'
        else:
            decision = None
        row.update(stability=stability, decision=decision, alternatives=alternatives)
    return {'contested': contested, 'signable': signable}
