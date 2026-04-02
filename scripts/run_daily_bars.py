"""Trigger one traderd daily bar delivery run through the operator API."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
stdlib_platform = sys.modules.get('platform')
if stdlib_platform is not None and not hasattr(stdlib_platform, '__path__'):
    sys.modules.pop('platform', None)

from platform.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description='Trigger traderd daily bar delivery.')
    parser.add_argument('--config', default=str(PROJECT_ROOT / 'config' / 'service.yaml'))
    parser.add_argument('--issued-by', default='scheduler')
    args = parser.parse_args()

    config = load_config(args.config)
    url = f'http://{config.operator_api.host}:{config.operator_api.port}/daily-bars/run'
    payload = json.dumps({'issued_by': args.issued_by}).encode('utf-8')
    request = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode('utf-8')
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8')
        print(body)
        return 1
    except OSError as exc:
        print(json.dumps({'error': str(exc), 'url': url}))
        return 1

    print(body)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
