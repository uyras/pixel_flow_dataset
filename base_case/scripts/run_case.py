#!/usr/bin/env python3
"""Serial generation, mesh checks and steady solve. Does not erase results."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from generate_case import generate
from check_result import inspect

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'parameters.json')
    parser.add_argument('--case', type=Path, default=ROOT)
    args = parser.parse_args()
    case = args.case.resolve()
    try:
        for cmd in ('blockMesh', 'checkMesh', 'foamRun'):
            if shutil.which(cmd) is None:
                raise ValueError(f'{cmd} not found: source the OpenFOAM Foundation 14 etc/bashrc first')
        version = os.environ.get('WM_PROJECT_VERSION')
        if version and version != '14':
            raise ValueError(f'Expected OpenFOAM Foundation 14, environment has {version}')
        summary = generate(args.config.resolve(), case)
        print(f"Mesh: {summary['cells']} cells, {summary['fluid_regions']} fluid regions", flush=True)
        for cmd in (['blockMesh'], ['checkMesh', '-allTopology', '-allGeometry'], ['foamRun']):
            name = cmd[0]
            log = case/f'log.{name}'
            print(f'Running {name}; log: {log}', flush=True)
            with log.open('w') as out:
                proc = subprocess.run(cmd, cwd=case, stdout=out, stderr=subprocess.STDOUT)
            if proc.returncode:
                raise ValueError(f'{name} failed ({proc.returncode}); inspect {log}')
            if name == 'checkMesh' and 'Mesh OK.' not in log.read_text():
                raise ValueError(f'Mesh checks did not pass; inspect {log}')
        result = inspect(case)
        print(f"Final residuals: {result['initial_residuals']}", flush=True)
        if not result['converged']:
            raise ValueError('Convergence thresholds were NOT reached. Final fields retained; see run_status.json')
        if not result['only_one_result_time']:
            raise ValueError('Expected exactly one saved result time; see run_status.json')
        print(f"CONVERGED at iteration {result['last_iteration']}; final fields saved", flush=True)
    except (ValueError, OSError) as e:
        parser.exit(2, f'ERROR: {e}\n')
    return 0

if __name__ == '__main__': sys.exit(main())
