import json
from pathlib import Path

from n225m_bt.research.datasets import write_json
from n225m_bt.research.history import related_history


def test_existing_batch_results_are_visible_across_campaigns(tmp_path):
    folder = tmp_path / '.research/batches/old/abc'
    write_json(folder / 'family.json', {'family_id': 'old', 'dataset': 'center',
        'factory': 'n225m_bt.strategies.test:create_strategy', 'space': {'window': [3, 5]},
        'hypothesis': 'compression breakout', 'uses': ['rolling_range']})
    write_json(folder / 'summary.json', {'identity': {'family_id': 'old', 'batch_id': 'abc'},
        'status': 'complete', 'coverage': {'planned': 2}, 'distribution': {'max_net_pnl_jpy': -10}})
    result = related_history(tmp_path, 'compression', 'center', campaign='new')
    assert result['records'][0]['tested_space']['space'] == {'window': [3, 5]}
    assert result['records'][0]['distribution']['max_net_pnl_jpy'] == -10
    assert result['records'][0]['evidence_type'] == 'saved_result_summary'
    assert related_history(tmp_path, 'compression', 'center')['indexed_families'] == 1


def test_failures_are_kept_and_corrupt_optional_history_does_not_block(tmp_path):
    write_json(tmp_path / '.research/campaigns/old/state.json', {
        'campaign_id': 'old', 'history': [{'family_id': 'old-1', 'status': 'failed', 'error': 'no data'}]})
    bad = tmp_path / '.research/campaigns/bad/state.json'
    bad.parent.mkdir(parents=True)
    bad.write_text('{broken')
    result = related_history(tmp_path, '', '', campaign='new')
    assert result['records'][0]['status'] == 'failed'
    assert result['warnings']


def test_index_refreshes_changed_summary(tmp_path):
    folder = tmp_path / '.research/batches/f/a'
    write_json(folder / 'family.json', {'dataset': 'center'})
    write_json(folder / 'summary.json', {'identity': {'family_id': 'f'}, 'status': 'partial'})
    assert related_history(tmp_path, '', 'center')['records'][0]['status'] == 'partial'
    write_json(folder / 'summary.json', {'identity': {'family_id': 'f'}, 'status': 'complete'})
    assert related_history(tmp_path, '', 'center')['records'][0]['status'] == 'complete'
