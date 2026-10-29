#!/usr/bin/env python3
"""Collect converged OpenFOAM cases into a compressed NPZ dataset."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import os
import subprocess
import sys
import tempfile
import zipfile

import numpy as np

ROOT = Path(__file__).resolve().parent
NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'


def clean(text):
    return re.sub(r'//[^\n]*|/\*.*?\*/', '', text, flags=re.S)


def block(text, name):
    match = re.search(r'\b' + re.escape(name) + r'\s*\{', text)
    if not match:
        raise ValueError(f'отсутствует блок {name}')
    start = match.end()
    depth = 1
    for i in range(start, len(text)):
        depth += (text[i] == '{') - (text[i] == '}')
        if not depth:
            return text[start:i]
    raise ValueError(f'незакрытый блок {name}')


def field_values(text, key, components, uniform_count=None):
    vector = r'\(\s*(' + NUMBER + r')\s+(' + NUMBER + r')\s+(' + NUMBER + r')\s*\)'
    item = vector if components == 3 else '(' + NUMBER + ')'
    match = re.search(r'\b' + re.escape(key) + r'\s+(uniform|nonuniform)\s+', text)
    if not match:
        raise ValueError(f'отсутствует {key} uniform/nonuniform')
    rest = text[match.end():]
    if match.group(1) == 'uniform':
        value = re.match(item + r'\s*;', rest)
        if not value or uniform_count is None:
            raise ValueError(f'не удалось прочитать uniform {key} или определить размер')
        values = [float(x) for x in value.groups()] * uniform_count
    else:
        header = re.match(r'List\s*<\s*(scalar|vector)\s*>\s*(\d+)\s*\(', rest)
        if not header or header.group(1) != ('vector' if components == 3 else 'scalar'):
            raise ValueError(f'неверный тип списка {key}')
        count = int(header.group(2))
        pos = header.end()
        values = []
        for _ in range(count):
            value = re.match(r'\s*' + item, rest[pos:])
            if not value:
                raise ValueError(f'неверный элемент списка {key}')
            values.extend(float(x) for x in value.groups())
            pos += value.end()
        if not re.match(r'\s*\)\s*;', rest[pos:]):
            raise ValueError(f'неверное окончание списка {key}')
        if uniform_count is not None and count != uniform_count:
            raise ValueError(f'неверное число элементов {key}: {count}, ожидалось {uniform_count}')
    if not all(math.isfinite(x) for x in values):
        raise ValueError(f'нечисловое или бесконечное значение {key}')
    return values


def metadata_array(metadata):
    data = json.dumps(metadata, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return np.frombuffer(data, dtype=np.uint8)


def read_metadata(archive):
    data = archive['metadata']
    if data.dtype != np.uint8 or data.ndim != 1:
        raise ValueError('некорректные метаданные NPZ')
    metadata = json.loads(data.tobytes().decode('utf-8'))
    if not isinstance(metadata, dict) or not isinstance(metadata.get('cases'), list):
        raise ValueError('некорректные метаданные NPZ')
    return metadata


def read_ascii(path):
    text = clean(path.read_text(encoding='utf-8'))
    if not re.search(r'\bformat\s+ascii\s*;', block(text, 'FoamFile')):
        raise ValueError(f'{path}: поддерживается только формат OpenFOAM ascii')
    return text


def result_time(case):
    times = []
    for p in case.iterdir():
        if p.is_dir():
            try:
                value = float(p.name)
            except ValueError:
                continue
            if math.isfinite(value) and value > 0:
                times.append((value, p))
    if not times:
        raise ValueError('нет каталога расчётного времени')
    return max(times, key=lambda pair: (pair[0], pair[1].name))[1]


def collect(case, time):
    boundary = read_ascii(case / 'constant/polyMesh/boundary')
    inlet = block(boundary, 'inlet')
    count_match = re.search(r'\bnFaces\s+(\d+)\s*;', inlet)
    if not count_match:
        raise ValueError('не найдено число входных граней')
    inlet_count = int(count_match.group(1))
    u_text = read_ascii(time / 'U')
    p_text = read_ascii(time / 'p')
    # OpenFOAM computes cell centres in an isolated copy, preserving the source case.
    with tempfile.TemporaryDirectory(prefix='pixel-flow-centres-') as tmp:
        tmp = Path(tmp)
        shutil.copytree(case / 'system', tmp / 'system')
        shutil.copytree(case / 'constant', tmp / 'constant')
        shutil.copytree(time, tmp / time.name)
        proc = subprocess.run(['foamPostProcess', '-case', str(tmp), '-func', 'writeCellCentres', '-latestTime'],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if proc.returncode:
            raise ValueError('foamPostProcess не смог вычислить центры ячеек:\n' + proc.stdout[-4000:])
        centers_text = read_ascii(tmp / time.name / 'C')
    centers = field_values(centers_text, 'internalField', 3)
    cells = len(centers) // 3
    if not cells:
        raise ValueError('сетка не содержит ячеек')
    pressure = field_values(p_text, 'internalField', 1, cells)
    velocity = field_values(u_text, 'internalField', 3, cells)
    inlet_u = field_values(block(block(u_text, 'boundaryField'), 'inlet'), 'value', 3, inlet_count)
    params = json.loads((case / 'case_summary.json').read_text(encoding='utf-8'))['parameters']
    speed = params['U_in']
    if type(speed) not in (float, int) or not math.isfinite(speed):
        raise ValueError('некорректный U_in')
    return cells, centers, pressure, velocity, inlet_u, speed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases', nargs='?', type=Path, help='каталог кейсов (по умолчанию output из dataset_settings.json)')
    parser.add_argument('--output', type=Path, default=Path('results.npz'), help='сжатый NPZ-файл датасета')
    parser.add_argument('--append', action='store_true', help='добавлять только новые завершённые кейсы')
    args = parser.parse_args()
    tmp_path = None
    try:
        cases = (args.cases if args.cases is not None else ROOT / json.loads((ROOT / 'dataset_settings.json').read_text())['output']).resolve(strict=True)
        if not cases.is_dir():
            raise ValueError(f'{cases} не является каталогом')
        output = args.output.resolve()
        if output.exists() and not args.append:
            raise ValueError(f'{output} уже существует; используйте --append или другой файл')
        if args.append and not output.is_file():
            raise ValueError('--append требует существующий датасет')
        metadata = {'version': 1, 'cases_root': str(cases), 'cases': []}
        arrays = {}
        if args.append:
            with np.load(output, allow_pickle=False) as old:
                metadata = read_metadata(old)
                if metadata.get('version') != 1 or metadata.get('cases_root') != str(cases):
                    raise ValueError('несовместимый датасет или другой исходный каталог кейсов')
                arrays = {key: old[key] for key in old.files if key != 'metadata'}
        existing = {item['name'] for item in metadata['cases']}
        added = skipped = 0
        errors = []
        for case in sorted(p for p in cases.iterdir() if p.is_dir()):
            if case.name in existing:
                skipped += 1
                continue
            try:
                try:
                    status = json.loads((case / 'run_status.json').read_text(encoding='utf-8'))
                except FileNotFoundError:
                    continue
                if not isinstance(status, dict) or type(status.get('converged')) is not bool or type(status.get('only_one_result_time')) is not bool:
                    raise ValueError('некорректный run_status.json')
                if not (status['converged'] and status['only_one_result_time']):
                    continue
                time = result_time(case)
                cells, centers, pressure, velocity, inlet_u, speed = collect(case, time)
                centers = np.asarray(centers, dtype='<f8').reshape(cells, 3)
                mesh_key = 'meshes/' + hashlib.sha256(centers.tobytes()).hexdigest()
                case_key = f'cases/{len(metadata["cases"]):08d}'
                p_data = np.asarray(pressure, dtype='<f8').reshape(cells)
                u_data = np.asarray(velocity, dtype='<f8').reshape(cells, 3)
                inlet_data = np.asarray(inlet_u, dtype='<f8').reshape(-1, 3)
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
                errors.append(f'{case.name}: {exc}')
                continue
            arrays.setdefault(mesh_key, centers)
            arrays[case_key + '/p'] = p_data
            arrays[case_key + '/U'] = u_data
            arrays[case_key + '/inlet_U'] = inlet_data
            metadata['cases'].append({'name': case.name, 'key': case_key, 'mesh': mesh_key,
                                      'time': time.name, 'U_in': speed})
            added += 1
        if not args.append or added:
            arrays['metadata'] = metadata_array(metadata)
            # Publish a complete replacement atomically, leaving the original intact on failure.
            with tempfile.NamedTemporaryFile(prefix='.pixel-flow-', suffix='.npz', dir=output.parent, delete=False) as tmp:
                tmp_path = Path(tmp.name)
                np.savez_compressed(tmp, **arrays)
            os.replace(tmp_path, output)
        tmp_path = None
        print(f'Добавлено: {added}; уже в датасете: {skipped}; ошибок: {len(errors)}')
        for error in errors:
            print(error, file=sys.stderr)
        return 1 if errors else 0
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(f'Ошибка: {exc}', file=sys.stderr)
        return 1
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(main())
