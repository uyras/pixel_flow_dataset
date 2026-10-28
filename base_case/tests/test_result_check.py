import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_result import inspect

class ResultCheckTests(unittest.TestCase):
    def check(self, log, saved='10'):
        with tempfile.TemporaryDirectory() as d:
            case=Path(d)
            (case/'case_summary.json').write_text(json.dumps({'parameters':{'p_residual':1e-5,'U_residual':1e-6}}))
            (case/'log.foamRun').write_text(log)
            if saved:
                (case/saved).mkdir()
                for f in ('U','p'):(case/saved/f).touch()
            return inspect(case)

    def log(self, p='9e-6', ux='5e-7', uy='9e-7', end=True):
        return (f'Time = 10s\nSolving for Ux, Initial residual = {ux}\n'
                f'Solving for Uy, Initial residual = {uy}\n'
                f'Solving for p, Initial residual = {p}\n'+('End\n' if end else ''))

    def test_success_with_unit_suffix(self):
        r=self.check(self.log())
        self.assertTrue(r['converged']);self.assertEqual(r['last_iteration'],10)

    def test_cap_without_convergence(self):
        self.assertFalse(self.check(self.log(p='0.01'))['converged'])

    def test_one_velocity_component_fails(self):
        self.assertFalse(self.check(self.log(uy='0.01'))['converged'])

    def test_fields_must_match_last_iteration(self):
        self.assertFalse(self.check(self.log(),saved='9')['converged'])
        self.assertFalse(self.check(self.log(),saved=None)['converged'])

    def test_incomplete_log(self):
        self.assertFalse(self.check(self.log(end=False))['converged'])

if __name__=='__main__':unittest.main()
