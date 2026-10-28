#!/usr/bin/env python3
"""Быстро показать состояние непосредственных подкаталогов набора кейсов."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def inspect_case(case):
    """Read the small final status, or identify the latest available run log."""
    status_path = case / 'run_status.json'
    missing = object()
    try:
        with status_path.open(encoding='utf-8') as stream:
            status = json.load(stream)
    except FileNotFoundError:
        status = missing
    except (OSError, ValueError) as exc:
        return 'ошибка статуса', str(exc)
    if status is not missing:
        if (not isinstance(status, dict) or
                type(status.get('converged')) is not bool or
                type(status.get('only_one_result_time')) is not bool):
            return 'ошибка статуса', 'некорректный run_status.json'
        if status['converged'] and status['only_one_result_time']:
            return 'завершён', f"итерация {status.get('last_iteration', '?')}"
        return 'неуспешный результат', 'см. run_status.json'

    for name in ('foamRun', 'checkMesh', 'blockMesh'):
        log = case / f'log.{name}'
        try:
            with log.open('rb') as stream:
                stream.seek(0, os.SEEK_END)
                stream.seek(max(0, stream.tell() - 8192))
                tail = stream.read().decode('utf-8', errors='replace')
        except FileNotFoundError:
            continue
        except OSError as exc:
            return 'ошибка чтения', str(exc)
        if any(marker in tail for marker in ('FOAM FATAL', 'Floating point exception', 'Segmentation fault')):
            return 'ошибка в журнале', f'log.{name}'
        return 'без итогового статуса', f'последний журнал: log.{name}'
    return 'не запускался', 'журналы и итоговый статус отсутствуют'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases', nargs='?', type=Path,
                        help='каталог кейсов (по умолчанию output из dataset_settings.json)')
    parser.add_argument('--details', action='store_true', help='показать каждый кейс')
    args = parser.parse_args()
    try:
        if args.cases is None:
            with (ROOT / 'dataset_settings.json').open(encoding='utf-8') as stream:
                output = json.load(stream)['output']
            if not isinstance(output, str) or not output.strip():
                raise ValueError('output должен быть непустой строкой')
            cases = ROOT / output
        else:
            cases = args.cases
        cases = cases.resolve()
        counts = Counter()
        details = []
        with os.scandir(cases) as entries:
            for entry in entries:
                if entry.is_dir():
                    state, reason = inspect_case(Path(entry.path))
                    counts[state] += 1
                    if args.details:
                        details.append((entry.name, state, reason))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Ошибка: {exc}', file=sys.stderr)
        return 1
    print(f'Каталог: {cases}\nВсего кейсов: {sum(counts.values())}')
    for state, count in sorted(counts.items()):
        print(f'  {state}: {count}')
    if args.details:
        for name, state, reason in sorted(details):
            print(f'{name}: {state} ({reason})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
