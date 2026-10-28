#!/usr/bin/env python3
"""Remove only generated mesh, numerical result directories and known run logs."""
import argparse
from pathlib import Path
import shutil
from generate_case import is_time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--case', type=Path, default=ROOT)
args = parser.parse_args()
case = args.case.resolve()
if not (case/'case_summary.json').is_file():
    parser.error('Refusing to clean a directory without case_summary.json')
paths = [case/'constant/polyMesh', case/'run_status.json']
paths += [case/f'log.{cmd}' for cmd in ('blockMesh', 'checkMesh', 'foamRun')]
paths += [p for p in case.iterdir() if p.is_dir() and is_time(p.name) and float(p.name) != 0]
for p in paths:
    if p.is_symlink(): p.unlink()
    elif p.is_dir(): shutil.rmtree(p)
    elif p.is_file(): p.unlink()
    else: continue
    print(f'Removed {p}')
print('Initial fields, parameters and scripts retained. Allrun regenerates dictionaries.')
