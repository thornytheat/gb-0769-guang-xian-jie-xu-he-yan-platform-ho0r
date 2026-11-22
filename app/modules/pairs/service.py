from bisect import bisect_left, bisect_right

from .ambiguity import optimal_context, rigid
from .optimal import best_pairs


def join(calibrated):
    a, b = [calibrated['aligned'][key] for key in ('a','b')]
    tolerance = calibrated['settings']['pair_tol_mm']
    left, right = [r['chain_mm'] for r in a], [r['chain_mm'] for r in b]
    indices = best_pairs(left, right, tolerance)
    context = optimal_context(left, right, tolerance)
    used_a, used_b = set(), set()
    pairs = []
    for i, j in indices:
        used_a.add(i)
        used_b.add(j)
        x, y = left[i], right[j]
        candidates = b[bisect_left(right, x-tolerance):bisect_right(right, x+tolerance)]
        pairs.append({'pair': f'P{len(pairs)+1:03d}', 'a': a[i], 'b': b[j], 'span_mm': abs(x-y),
                      'midpoint_half_mm': x+y, 'possible_b': [r['id'] for r in candidates],
                      'rigid': rigid(context, i, j),
                      'alt_a': [a[k]['id'] for k in context['partners_b'][j] if k != i],
                      'alt_b': [b[k]['id'] for k in context['partners_a'][i] if k != j]})
    singles = []
    for rows, others, chains, used, opposite, partners in ((a,b,right,used_a,'B',context['partners_a']),
                                                           (b,a,left,used_b,'A',context['partners_b'])):
        for i, row in enumerate(rows):
            if i not in used:
                x = row['chain_mm']
                competing = bisect_left(chains, x-tolerance) < bisect_right(chains, x+tolerance)
                singles.append({**row, 'code': 'PAIR_COMPETITION' if competing else f'NO_{opposite}_NEARBY',
                                'possible_partner': [others[k]['id'] for k in partners[i]]})
    ambiguous = any(not p['rigid'] for p in pairs) or any(s['possible_partner'] for s in singles)
    return {'pairs': pairs, 'singles': singles, 'pair_count': len(pairs), 'single_count': len(singles),
            'total_span_mm': sum(r['span_mm'] for r in pairs), 'balanced': len(a)+len(b) == 2*len(pairs)+len(singles),
            'ambiguous': ambiguous}
