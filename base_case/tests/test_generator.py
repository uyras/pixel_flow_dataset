#!/usr/bin/env python3
"""Topology and parameter tests; no third-party Python packages required."""
from collections import Counter
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import generate_case as g

class GeneratorTests(unittest.TestCase):
    def params(self, **changes):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'p.json';f.write_text(json.dumps(changes))
            return g.load_parameters(f)

    def check_topology(self, p):
        m=g.mesh_model(p)
        counts=Counter(tuple(sorted(b['ids'][i] for i in f))
                       for b in m['blocks'] for f in g.FACES)
        exposed=Counter(tuple(sorted(f)) for faces in m['patches'].values() for f in faces)
        self.assertTrue(all(n in (1,2) for n in counts.values()))
        self.assertEqual(exposed, Counter({f:1 for f,n in counts.items() if n==1}))
        self.assertEqual(m['n_cells'], round((8-sum(map(sum,p['solid_mask']))/p['L']**2)
                                            *p['effective_cells_per_meter']**2))
        # A shared block face must have the same fine-grid subdivision.
        interface_sizes={}
        for b in m['blocks']:
            a,c,_=b['counts']
            for face, fine in zip(g.FACES, (c,c,a,a,a*c,a*c)):
                key=tuple(sorted(b['ids'][i] for i in face))
                if key in interface_sizes:self.assertEqual(interface_sizes[key],fine)
                interface_sizes[key]=fine
        return m

    def test_default(self):
        m=self.check_topology(self.params())
        self.assertEqual((m['n_cells'],len(m['blocks']),m['cavities']),(25200,20,0))

    def test_each_square_independently_removed(self):
        for j in range(4):
            for i in range(4):
                mask=[[1]*4 for _ in range(4)];mask[j][i]=0
                m=self.check_topology(self.params(solid_mask=mask))
                self.assertEqual(m['n_cells'],25425)
                self.assertEqual(m['cavities'], int(0<i<3 and 0<j<3))

    def test_all_masks_L2(self):
        for bits in range(16):
            mask=[[(bits>>(j*2+i))&1 for i in range(2)] for j in range(2)]
            self.check_topology(self.params(L=2,solid_mask=mask))

    def test_checkerboard_and_empty(self):
        for mask in ([[0]*4 for _ in range(4)],
                     [[(i+j)%2 for i in range(4)] for j in range(4)]):
            self.check_topology(self.params(solid_mask=mask))

    def test_resolution(self):
        with self.assertRaises(ValueError):self.params(L=7)
        p=self.params(L=7,resolution_policy='round_up')
        self.assertEqual(p['effective_cells_per_meter'],70)
        self.check_topology(p)
        for L in (1,2,3,4,5,6,10,12,15,20,30,60):
            self.check_topology(self.params(L=L))

    def test_invalid_input(self):
        for changes in ({'L':0},{'L':True},{'U_in':float('nan')},{'nu':0},
                        {'solid_mask':[[1]]},{'uin':1}):
            with self.assertRaises(ValueError):self.params(**changes)

    def test_profile_and_write_controls(self):
        p=self.params(U_in=2.5,max_iterations=1234)
        m=g.mesh_model(p);u,_=g.fields(p,m)
        self.assertIn('(2.5 0 0)',u);self.assertIn('(-2.5 0 0)',u)
        self.assertNotIn('codedFixedValue',u)
        cd=g.dictionaries(p)['system/controlDict']
        self.assertIn('endTime 1234;',cd);self.assertIn('writeInterval 1234;',cd)
        self.assertIn('steadyState',g.dictionaries(p)['system/fvSchemes'])

if __name__=='__main__':unittest.main()
