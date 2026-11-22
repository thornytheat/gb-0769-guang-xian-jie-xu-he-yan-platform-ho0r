from app.modules.archive.identity import canonical, digest


def certify(record):
    stages = record['computed']
    design = stages['design']
    blockers = []
    if design['missing']:
        blockers.append('MISSING_JOINTS')
    if design['over_limit']:
        blockers.append('LOSS_OVER_LIMIT')
    if design.get('contested'):
        blockers.append('CONTESTED_JOINTS')
    if not design['design_count']:
        blockers.append('EMPTY_DESIGN')
    if any(line['source'] == 'design' and line['code'] != 'DUPLICATE_EVENT' for line in stages['trace']['isolated']):
        blockers.append('UNVERIFIED_DESIGN_ROWS')
    rows = design['rows']
    return {'inspection_id':record['inspection_id'], 'approved': not blockers,
            'blockers':blockers,
            'sign_now':[row['joint'] for row in rows if row.get('decision') == 'SIGN_NOW'],
            'hold_retest':[row['joint'] for row in rows if row.get('decision') == 'HOLD_RETEST'],
            'integrity_sha256':digest(canonical(record)), 'record':record}
