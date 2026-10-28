#!/usr/bin/env python3
"""Summarise final SIMPLE initial residuals; never call a capped run converged."""
import argparse
import json
import math
from pathlib import Path
import re
import sys

NUM = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'

def inspect(case):
    case = Path(case)
    text = (case/'log.foamRun').read_text(errors='replace')
    summary = json.loads((case/'case_summary.json').read_text())
    pars = summary['parameters']
    times = list(re.finditer(r'^Time = (\S+)', text, re.M))
    last = text[times[-1].start():] if times else text
    residuals = {}
    for field, value in re.findall(
            rf'Solving for (\w+), Initial residual = ({NUM})', last):
        residuals.setdefault(field, float(value))
    p_ok = 'p' in residuals and residuals['p'] < pars['p_residual']
    velocities = [v for k, v in residuals.items() if k in ('Ux', 'Uy', 'Uz', 'U')]
    u_ok = (all(k in residuals for k in ('Ux', 'Uy'))
            and max(velocities) < pars['U_residual'])
    fatal = bool(re.search(r'FOAM FATAL|Floating point exception|Segmentation fault', text))
    final_dirs = []
    for path in case.iterdir():
        if not path.is_dir(): continue
        try: value = float(path.name)
        except ValueError: continue
        if math.isfinite(value) and value > 0: final_dirs.append((value, path))
    final_dirs.sort()
    latest = final_dirs[-1][1] if final_dirs else None
    fields_saved = latest is not None and all((latest/f).is_file() for f in ('U', 'p'))
    finished = bool(re.search(r'^End\s*$', text, re.M))
    last_label = times[-1].group(1) if times else None
    last_number = re.match(NUM, last_label) if last_label else None
    iteration = float(last_number.group()) if last_number else None
    current_saved = latest is not None and iteration is not None and float(latest.name) == iteration
    result = dict(converged=bool(p_ok and u_ok and not fatal and fields_saved and finished and current_saved),
                  solver_reported_convergence='solution converged in' in text,
                  last_iteration=iteration, last_time_label=last_label,
                  solver_finished=finished,
                  initial_residuals=residuals,
                  thresholds=dict(p=pars['p_residual'], U=pars['U_residual']),
                  saved_result_times=[x.name for _, x in final_dirs],
                  only_one_result_time=len(final_dirs) == 1,
                  final_fields_saved=fields_saved, fatal_error=fatal)
    (case/'run_status.json').write_text(json.dumps(result, indent=2)+'\n')
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try: result = inspect(args.case)
    except (OSError, ValueError) as e: parser.exit(2, f'ERROR: {e}\n')
    print(json.dumps(result, indent=2))
    return 0 if result['converged'] and result['only_one_result_time'] else 2

if __name__ == '__main__': sys.exit(main())
