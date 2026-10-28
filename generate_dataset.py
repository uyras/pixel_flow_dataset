#!/usr/bin/env python3
"""Создать независимые OpenFOAM-кейсы из base_case, не запуская расчёты."""
import argparse
import csv
import json
import math
from pathlib import Path
import random
import shutil
import sys

ROOT = Path(__file__).resolve().parent
BASE = ROOT / 'base_case'
sys.path.insert(0, str(BASE / 'scripts'))
from generate_case import generate, load_parameters

SETTINGS = ROOT / 'dataset_settings.json'


def read_settings(path):
    settings = json.loads(path.read_text(encoding='utf-8'))
    keys = {'L', 'U_in', 'random_count', 'seed', 'output'}
    if not isinstance(settings, dict) or not keys <= set(settings) or set(settings) - keys - {'slurm'}:
        raise ValueError(f'Настройки должны содержать ключи {sorted(keys)} и необязательный slurm')
    sizes, speeds = settings['L'], settings['U_in']
    if (not isinstance(sizes, list) or not sizes or
            any(type(value) is not int or value < 2 for value in sizes) or
            len(set(sizes)) != len(sizes)):
        raise ValueError('L должен быть непустым списком различных целых чисел >= 2')
    if (not isinstance(speeds, list) or not speeds or
            any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0
                for value in speeds) or len(set(speeds)) != len(speeds)):
        raise ValueError('U_in должен быть непустым списком различных положительных чисел')
    if type(settings['random_count']) is not int or settings['random_count'] < 0:
        raise ValueError('random_count должен быть неотрицательным целым числом')
    if type(settings['seed']) is not int:
        raise ValueError('seed должен быть целым числом')
    if not isinstance(settings['output'], str) or not settings['output'].strip():
        raise ValueError('output должен быть непустой строкой')
    return settings


def masks(size, count, rng):
    """Строки маски идут снизу вверх; случайные маски уникальны для данного L."""
    main = [[int(i == j) for i in range(size)] for j in range(size)]
    anti = [[int(i + j == size - 1) for i in range(size)] for j in range(size)]
    cross = [[int(main[j][i] or anti[j][i]) for i in range(size)]
             for j in range(size)]
    invert = lambda mask: [[1 - value for value in row] for row in mask]
    fixed = [('empty', [[0] * size for _ in range(size)]),
             ('full', [[1] * size for _ in range(size)]),
             ('diagonal_main', main), ('diagonal_anti', anti),
             ('diagonal_main_inverse', invert(main)),
             ('diagonal_anti_inverse', invert(anti)),
             ('diagonals_both', cross), ('diagonals_both_inverse', invert(cross))]
    seen = {tuple(value for row in mask for value in row) for _, mask in fixed}
    if count > 2 ** (size * size) - len(seen):
        raise ValueError(f'Слишком много уникальных случайных масок для L={size}')
    yield from fixed
    for index in range(1, count + 1):
        while True:
            bits = tuple(rng.getrandbits(1) for _ in range(size * size))
            if bits not in seen:
                seen.add(bits)
                break
        yield f'random_{index:04d}', [list(bits[j * size:(j + 1) * size])
                                      for j in range(size)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=SETTINGS,
                        help='JSON-файл настроек генерации датасета')
    parser.add_argument('--output', type=Path, help='переопределить выходной каталог')
    parser.add_argument('--random-count', type=int, help='переопределить число случайных масок')
    parser.add_argument('--seed', type=int, help='переопределить seed')
    args = parser.parse_args()
    try:
        settings = read_settings(args.config)
        if args.random_count is not None:
            settings['random_count'] = args.random_count
        if args.seed is not None:
            settings['seed'] = args.seed
        if settings['random_count'] < 0:
            raise ValueError('random_count должен быть неотрицательным')
        # Относительный путь из JSON считается от папки файла настроек.
        output = (args.output if args.output is not None else
                  args.config.resolve().parent / settings['output']).resolve()
        if output == BASE or BASE in output.parents:
            raise ValueError('выходной каталог должен находиться вне base_case')
        if output.exists():
            raise ValueError(f'выходной каталог уже существует: {output}')
        base = json.loads((BASE / 'parameters.json').read_text(encoding='utf-8'))
        # Проверить входные параметры до создания выходного каталога.
        validated_base = load_parameters(BASE / 'parameters.json')
        if validated_base['resolution_policy'] == 'strict':
            for size in settings['L']:
                if validated_base['cells_per_meter'] % math.lcm(2, size):
                    raise ValueError(f'L={size} несовместим с cells_per_meter при strict')
        rng = random.Random(settings['seed'])
        all_masks = {size: list(masks(size, settings['random_count'], rng))
                     for size in settings['L']}
        output.mkdir(parents=True, exist_ok=False)
        rows = []
        for size, variants in all_masks.items():
            for name, mask in variants:
                uniform = name in ('empty', 'full')
                if uniform and size != settings['L'][0]:
                    continue
                for speed in settings['U_in']:
                    case_name = (f'{name}_U{speed}' if uniform else
                                 f'L{size}_{name}_U{speed}')
                    case = output / case_name
                    case.mkdir()
                    for filename in ('Allrun', 'Allclean'):
                        shutil.copy2(BASE / filename, case / filename)
                    shutil.copytree(BASE / 'scripts', case / 'scripts',
                                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                    params = dict(base, L=size, U_in=speed, solid_mask=mask)
                    config = case / 'parameters.json'
                    config.write_text(json.dumps(params, ensure_ascii=False, indent=2) + '\n',
                                      encoding='utf-8')
                    summary = generate(config, case)
                    rows.append(dict(case=case_name, L=size, mask=name, U_in=speed,
                                     cells=summary['cells'],
                                     closed_cavities=summary['closed_cavities']))
        with (output / 'manifest.csv').open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        (output / 'dataset_info.json').write_text(json.dumps(
            dict(seed=settings['seed'], random_masks_per_L=settings['random_count'],
                 sizes=settings['L'], speeds=settings['U_in'], cases=len(rows)), indent=2) + '\n',
            encoding='utf-8')
        print(f'Создано кейсов: {len(rows)}; каталог: {output}')
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f'Ошибка: {exc}\n')


if __name__ == '__main__':
    main()
