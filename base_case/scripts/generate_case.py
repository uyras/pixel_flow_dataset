#!/usr/bin/env python3
"""Generate a Foundation OpenFOAM 14 2-D blockMesh case, Python 3.9+."""
import argparse
from collections import deque
from fractions import Fraction as F
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = dict(L=4, U_in=1.0, rho=1.225, nu=1.506e-5,
                cells_per_meter=60, resolution_policy='strict',
                max_iterations=20000, p_residual=1e-5, U_residual=1e-6,
                solid_mask=None)
SIDES = ((-1, 0), (1, 0), (0, -1), (0, 1))
FACES = ((0, 4, 7, 3), (1, 2, 6, 5), (0, 1, 5, 4), (3, 7, 6, 2),
         (0, 3, 2, 1), (4, 5, 6, 7))

def header(obj, cls='dictionary', location='system'):
    return ("// Generated for OpenFOAM Foundation 14. Edit parameters.json, then regenerate.\n"
            "FoamFile\n{\n    version 2.0;\n    format ascii;\n"
            f'    class {cls};\n    location "{location}";\n    object {obj};\n}}\n\n')

def number(x):
    return format(float(x), '.16g')

def load_parameters(path):
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(raw, dict):
        raise ValueError('Parameters must be a JSON object')
    unknown = set(raw) - set(DEFAULTS)
    if unknown:
        raise ValueError(f'Unknown parameters: {sorted(unknown)}')
    p = {**DEFAULTS, **raw}
    for key in ('L', 'cells_per_meter', 'max_iterations'):
        if type(p[key]) is not int or p[key] < 1:
            raise ValueError(f'{key} must be a positive integer')
    for key in ('U_in', 'rho', 'nu', 'p_residual', 'U_residual'):
        if isinstance(p[key], bool) or not isinstance(p[key], (int, float)):
            raise ValueError(f'{key} must be a finite number')
        if not math.isfinite(p[key]) or p[key] <= 0:
            raise ValueError(f'{key} must be finite and > 0')
    if p['resolution_policy'] not in ('strict', 'round_up'):
        raise ValueError('resolution_policy must be strict or round_up')
    L = p['L']
    if p['solid_mask'] is None:
        p['solid_mask'] = [[1]*L for _ in range(L)]
    mask = p['solid_mask']
    if (not isinstance(mask, list) or len(mask) != L
        or any(not isinstance(row, list) or len(row) != L for row in mask)
        or any(type(v) is not int or v not in (0, 1) for row in mask for v in row)):
        raise ValueError('solid_mask must contain L rows of L integers, each 0 or 1')
    step = math.lcm(2, L)
    n = p['cells_per_meter']
    if n % step:
        if p['resolution_policy'] == 'strict':
            raise ValueError(f'Exact square mesh requires cells_per_meter divisible by '
                             f'lcm(2,L)={step}; choose another density or round_up')
        n = step * math.ceil(n / step)
    p['effective_cells_per_meter'] = n
    return p

def components(cells):
    remaining = set(cells)
    result = []
    while remaining:
        seed = min(remaining)
        remaining.remove(seed)
        part, queue = {seed}, deque([seed])
        while queue:
            i, j = queue.popleft()
            for di, dj in SIDES:
                q = i+di, j+dj
                if q in remaining:
                    remaining.remove(q)
                    part.add(q)
                    queue.append(q)
        result.append(part)
    return result

def mesh_model(p):
    L, n, mask = p['L'], p['effective_cells_per_meter'], p['solid_mask']
    xs = [F(-1)] + [F(i, L) for i in range(L+1)] + [F(3)]
    ys = [F(-1)] + [F(-1, 2) + F(j, L) for j in range(L+1)] + [F(1)]
    nx, ny = len(xs)-1, len(ys)-1
    fluid = {(i, j) for j in range(ny) for i in range(nx)
             if not (1 <= i <= L and 1 <= j <= L and mask[j-1][i-1])}
    regions = components(fluid)
    closed = [r for r in regions if not any(i == 0 or i == nx-1 for i, j in r)]
    anchors = {}
    for k, region in enumerate(closed, 1):
        i, j = min(region)
        side = next(s for s, (di, dj) in enumerate(SIDES)
                    if (i+di, j+dj) not in fluid)
        anchors[(i, j, side)] = f'cavityRef_{k}'

    # Split a geometric vertex when two fluid sectors touch only at a corner.
    # Face-neighbouring blocks still share the same vertex labels.
    stars = {}
    def corner_key(i, j, cell):
        if (i, j) not in stars:
            incident = {(a, b) for a in (i-1, i) for b in (j-1, j)
                        if (a, b) in fluid}
            stars[(i, j)] = {c: min(r) for r in components(incident) for c in r}
        return i, j, stars[(i, j)][cell]

    vertices, vertex_ids, blocks = [], {}, []
    patches = {name: [] for name in ('inlet', 'outlet', 'lowerWall', 'upperWall',
                                    'body', 'frontAndBack')}
    for name in anchors.values():
        patches[name] = []
    for i, j in sorted(fluid, key=lambda c: (c[1], c[0])):
        ids = []
        for z in (0, 1):
            for a, b in ((i, j), (i+1, j), (i+1, j+1), (i, j+1)):
                key = (*corner_key(a, b, (i, j)), z)
                if key not in vertex_ids:
                    vertex_ids[key] = len(vertices)
                    vertices.append((xs[a], ys[b], F(z, 100)))
                ids.append(vertex_ids[key])
        ni, nj = (xs[i+1]-xs[i])*n, (ys[j+1]-ys[j])*n
        assert ni.denominator == nj.denominator == 1
        blocks.append(dict(cell=(i, j), ids=ids, counts=(int(ni), int(nj), 1)))
        for s, (di, dj) in enumerate(SIDES):
            if (i+di, j+dj) in fluid:
                continue
            if i == 0 and s == 0: name = 'inlet'
            elif i == nx-1 and s == 1: name = 'outlet'
            elif j == 0 and s == 2: name = 'lowerWall'
            elif j == ny-1 and s == 3: name = 'upperWall'
            else: name = anchors.get((i, j, s), 'body')
            patches[name].append(tuple(ids[q] for q in FACES[s]))
        for s in (4, 5):
            patches['frontAndBack'].append(tuple(ids[q] for q in FACES[s]))
    patches = {k: v for k, v in patches.items() if v}
    return dict(vertices=vertices, blocks=blocks, patches=patches,
                regions=len(regions), cavities=len(closed),
                n_cells=sum(math.prod(b['counts']) for b in blocks))

def block_mesh_text(m):
    out = [header('blockMeshDict'), 'convertToMeters 1;\n\nvertices\n(\n']
    out += ['    ('+' '.join(map(number, v))+')\n' for v in m['vertices']]
    out += [');\n\nblocks\n(\n']
    for b in m['blocks']:
        out.append('    hex ('+' '.join(map(str, b['ids']))+') ('
                   +' '.join(map(str, b['counts']))+') simpleGrading (1 1 1)\n')
    out += [');\n\nedges ();\n\nboundary\n(\n']
    for name, faces in m['patches'].items():
        typ = 'empty' if name == 'frontAndBack' else (
            'patch' if name in ('inlet', 'outlet') else 'wall')
        out.append(f'    {name}\n    {{\n        type {typ};\n        faces\n        (\n')
        out += ['            ('+' '.join(map(str, f))+')\n' for f in faces]
        out.append('        );\n    }\n')
    out += [');\n\nmergePatchPairs ();\n']
    return ''.join(out)

def fields(p, m):
    u = header('U', 'volVectorField', '0')
    u += 'dimensions [0 1 -1 0 0 0 0];\ninternalField uniform (0 0 0);\nboundaryField\n{\n'
    pr = header('p', 'volScalarField', '0')
    pr += 'dimensions [0 2 -2 0 0 0 0];\ninternalField uniform 0;\nboundaryField\n{\n'
    speed = number(p['U_in'])
    for name in m['patches']:
        if name == 'inlet':
            bc = ('type fixedProfile;\n        profile polynomial\n        (\n'
                  f'            ({speed} 0 0)\n'
                  '            (0 0 0)\n'
                  f'            (-{speed} 0 0)\n'
                  '        );\n        direction (0 1 0);\n        origin 0;')
        elif name == 'outlet': bc = 'type zeroGradient;'
        elif name == 'frontAndBack': bc = 'type empty;'
        else: bc = 'type noSlip;'
        u += f'    {name}\n    {{\n        {bc}\n    }}\n'
        if name == 'frontAndBack': bc = 'type empty;'
        elif name == 'outlet' or name.startswith('cavityRef_'):
            bc = 'type fixedValue;\n        value uniform 0;'
        else: bc = 'type zeroGradient;'
        pr += f'    {name}\n    {{\n        {bc}\n    }}\n'
    return u+'}\n', pr+'}\n'

def dictionaries(p):
    maxit = p['max_iterations']
    control = header('controlDict') + f'''application foamRun;
solver incompressibleFluid;
startFrom startTime;
startTime 0;
stopAt endTime;
endTime {maxit};
deltaT 1;
writeControl timeStep;
writeInterval {maxit};
purgeWrite 0;
writeFormat ascii;
writePrecision 12;
writeCompression off;
timeFormat general;
timePrecision 12;
runTimeModifiable false;
'''
    schemes = header('fvSchemes') + '''ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; }
divSchemes
{
    default none;
    div(phi,U) bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
'''
    solution = header('fvSolution') + '''solvers
{
    p
    {
        solver GAMG;
        tolerance 1e-8;
        relTol 0.01;
        smoother GaussSeidel;
    }
    U
    {
        solver smoothSolver;
        smoother symGaussSeidel;
        tolerance 1e-9;
        relTol 0.01;
    }
}
SIMPLE
{
    nNonOrthogonalCorrectors 0;
    residualControl
    {
''' + f"        p {number(p['p_residual'])};\n        U {number(p['U_residual'])};\n" + '''    }
}
relaxationFactors
{
    fields { p 0.3; }
    equations { U 0.7; }
}
'''
    props = header('physicalProperties', location='constant') + (
        f"viscosityModel constant;\nnu [0 2 -1 0 0 0 0] {number(p['nu'])};\n"
        f"// Constant density for dimensional pressure conversion; not used by the incompressible solver.\n"
        f"rho [1 -3 0 0 0 0 0] {number(p['rho'])};\n")
    mt = header('momentumTransport', location='constant') + 'simulationType laminar;\n'
    return {'system/controlDict': control, 'system/fvSchemes': schemes,
            'system/fvSolution': solution, 'constant/physicalProperties': props,
            'constant/momentumTransport': mt}

def preview_svg(p):
    L = p['L']
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 520">',
             '<rect width="880" height="520" fill="white"/>',
             '<text x="40" y="30" font-family="sans-serif" font-size="20">OpenFOAM 14 — mask and channel</text>',
             '<rect x="40" y="60" width="800" height="400" fill="#eaf5ff" stroke="#132b42" stroke-width="2"/>']
    # Mapping: screen x=240+200*x, screen y=260-200*y.
    for j, row in enumerate(p['solid_mask']):
        for i, solid in enumerate(row):
            x, y, s = 240+200*i/L, 360-200*(j+1)/L, 200/L
            parts.append(f'<rect x="{x}" y="{y}" width="{s}" height="{s}" fill="{("#364152" if solid else "#eaf5ff")}" stroke="#8695a4" stroke-width="0.7"/>')
            if L <= 8:
                parts.append(f'<text x="{x+s/2}" y="{y+s/2+4}" text-anchor="middle" fill="{("white" if solid else "#132b42")}" font-family="monospace" font-size="11">{i},{j}</text>')
    parts += ['<circle cx="240" cy="260" r="4" fill="#d1495b"/>',
              '<text x="248" y="254" font-family="sans-serif" font-size="14">(0,0)</text>',
              '<text x="40" y="490" font-family="sans-serif" font-size="14">x: -1 to 3 m; y: -1 to 1 m; z: 0 to 0.01 m. Dark = solid, pale = fluid.</text>',
              '</svg>']
    return '\n'.join(parts)

def generate(config, output):
    p = load_parameters(config)
    m = mesh_model(p)
    files = dictionaries(p)
    u, pr = fields(p, m)
    files.update({'0/U': u, '0/p': pr, 'system/blockMeshDict': block_mesh_text(m),
                  'geometry.svg': preview_svg(p), 'channel.foam': ''})
    summary = dict(parameters=p, bounds=dict(x=[-1, 3], y=[-1, 1], z=[0, 0.01]),
                   blocks=len(m['blocks']), cells=m['n_cells'],
                   fluid_regions=m['regions'], closed_cavities=m['cavities'],
                   solid_area_m2=sum(map(sum, p['solid_mask']))/p['L']**2,
                   dx_m=1/p['effective_cells_per_meter'],
                   Re_1m=p['U_in']/p['nu'],
                   pressure_Pa_per_field_unit=p['rho'],
                   generated_files=sorted(files))
    files['case_summary.json'] = json.dumps(summary, ensure_ascii=False, indent=2)+'\n'
    output = Path(output)
    has_results = output.exists() and any(
        q.is_dir() and is_time(q.name) and float(q.name) != 0 for q in output.iterdir())
    if (output/'constant/polyMesh').exists() or has_results:
        raise ValueError('Existing mesh/results: use a new output directory or ./Allclean first')
    for name, text in files.items():
        dest = output/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding='utf-8')
    return summary

def is_time(name):
    try: return math.isfinite(float(name)) and float(name) >= 0
    except ValueError: return False

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'parameters.json')
    parser.add_argument('--output', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        s = generate(args.config, args.output)
    except (ValueError, OSError) as e:
        parser.exit(2, f'ERROR: {e}\n')
    print(f"Generated {args.output.resolve()}: {s['cells']} cells, "
          f"{s['blocks']} blocks, {s['closed_cavities']} closed cavities; "
          f"density {s['parameters']['effective_cells_per_meter']} cells/m")

if __name__ == '__main__': main()
