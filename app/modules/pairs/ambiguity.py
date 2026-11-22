"""Equally-good optimal pairings: who can change partners or stand alone.

The pairing score is lexicographic (pair count, negated total span).  Two
matchings with the same score are equally贴合 evidence sets.  Forward and
backward dynamic programming mark every event pair that appears in at least
one optimal matching and every event that can stand alone in one, so verdicts
can be checked against the whole tie class instead of a single picked set.
"""


def _forward(left, right, tolerance, forbidden=frozenset()):
    n, m = len(left), len(right)
    table = [[(0, 0)] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        row, prev = table[i], table[i - 1]
        li = left[i - 1]
        for j in range(1, m + 1):
            best = prev[j] if prev[j] >= row[j - 1] else row[j - 1]
            delta = abs(li - right[j - 1])
            if delta <= tolerance and (i - 1, j - 1) not in forbidden:
                count, neg_span = prev[j - 1]
                matched = (count + 1, neg_span - delta)
                if matched > best:
                    best = matched
            row[j] = best
    return table


def optimal_context(left, right, tolerance):
    """Characterise every optimal matching of the two ordered chainage lists."""
    n, m = len(left), len(right)
    fwd = _forward(left, right, tolerance)
    bwd = [[(0, 0)] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        row, nxt = bwd[i], bwd[i + 1]
        li = left[i]
        for j in range(m - 1, -1, -1):
            best = nxt[j] if nxt[j] >= row[j + 1] else row[j + 1]
            delta = abs(li - right[j])
            if delta <= tolerance:
                count, neg_span = bwd[i + 1][j + 1]
                matched = (count + 1, neg_span - delta)
                if matched > best:
                    best = matched
            row[j] = best
    score = fwd[n][m]
    partners_a = [[] for _ in range(n)]
    partners_b = [[] for _ in range(m)]
    for i in range(n):
        li, prefix = left[i], fwd[i]
        for j in range(m):
            delta = abs(li - right[j])
            if delta <= tolerance:
                (c1, s1), (c2, s2) = prefix[j], bwd[i + 1][j + 1]
                if (c1 + 1 + c2, s1 - delta + s2) == score:
                    partners_a[i].append(j)
                    partners_b[j].append(i)
    a_single = [any((fwd[i][j][0] + bwd[i + 1][j][0], fwd[i][j][1] + bwd[i + 1][j][1]) == score
                    for j in range(m + 1)) for i in range(n)]
    b_single = [any((fwd[i][j][0] + bwd[i][j + 1][0], fwd[i][j][1] + bwd[i][j + 1][1]) == score
                    for i in range(n + 1)) for j in range(m)]
    return {'score': score, 'partners_a': partners_a, 'partners_b': partners_b,
            'a_can_be_single': a_single, 'b_can_be_single': b_single,
            'left': left, 'right': right, 'tolerance': tolerance}


def rigid(context, i, j):
    """True when pair (i, j) appears in every optimal matching."""
    return (context['partners_a'][i] == [j] and not context['a_can_be_single'][i]
            and context['partners_b'][j] == [i] and not context['b_can_be_single'][j])


def avoid_score(context, forbidden):
    """Best score reachable when the given (i, j) pairs may not be used."""
    table = _forward(context['left'], context['right'], context['tolerance'], forbidden)
    return table[len(context['left'])][len(context['right'])]
