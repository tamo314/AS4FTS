"""Copy an existing H02 grid, changing only its factory/version and run label."""
from __future__ import annotations

import argparse
from pathlib import Path

from n225m_bt.research.datasets import write_json
from n225m_bt.research.runner import read_spec


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve() == args.output.resolve() or args.output.exists():
        raise ValueError('use a new output file; the original specification is preserved')
    spec = read_spec(args.source)
    if spec.get('factory') not in {
        'n225m_bt.strategies.opening_range_failure_fade:create_strategy',
        'n225m_bt.strategies.opening_range_failure:create_strategy'}:
        raise ValueError('this helper only migrates the reviewed H02 family')
    depth = spec.get('parameters', {}).get('reentry_depth_fraction', 0)
    axes = spec.get('space', {}).get('reentry_depth_fraction', [depth])
    if depth != 0 or axes != [0] or spec.get('variants'):
        raise ValueError('only the reviewed zero-depth H02 grid is supported; no implicit narrowing')
    spec['factory'] = 'n225m_bt.strategies.opening_range_failure:create_strategy'
    spec['family_id'] = spec['family_id'] + '-contract-v2'
    spec['implementation_required'] = False
    spec['uses'] = sorted(set(spec.get('uses', [])) | {'opening_range_failure_h02_v2'})
    spec['correction_note'] = 'Bounded [L,H] return, inclusive timeout, monitoring end exclusive, rearm after expiry.'
    write_json(args.output, spec)
    print(args.output)


if __name__ == '__main__':
    main()
