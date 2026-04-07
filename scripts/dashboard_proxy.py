from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

HOP_BY_HOP_HEADERS = {
    'connection',
    'keep-alive',
    'proxy-authenticate',
    'proxy-authorization',
    'te',
    'trailers',
    'transfer-encoding',
    'upgrade',
}


def _tailscale_ipv4() -> str:
    result = subprocess.run(['tailscale', 'ip', '-4'], capture_output=True, text=True, timeout=5, check=True)
    value = result.stdout.strip().splitlines()
    if not value:
        raise RuntimeError('tailscale ip -4 returned no addresses')
    return value[0].strip()


def _required_env(name: str) -> str:
    value = os.environ.get(name, '').strip()
    if not value:
        raise RuntimeError(f'missing required environment variable: {name}')
    return value


def main() -> int:
    username = _required_env('DASHBOARD_PROXY_USERNAME')
    password = _required_env('DASHBOARD_PROXY_PASSWORD')
    bind_host = os.environ.get('DASHBOARD_PROXY_BIND_HOST', '').strip() or _tailscale_ipv4()
    bind_port = int(os.environ.get('DASHBOARD_PROXY_PORT', '18080'))
    target = os.environ.get('DASHBOARD_PROXY_TARGET', 'http://127.0.0.1:8080').strip()
    auth_token = 'Basic ' + base64.b64encode(f'{username}:{password}'.encode('utf-8')).decode('ascii')

    class Handler(BaseHTTPRequestHandler):
        server_version = 'traderd-dashboard-proxy/1.0'

        def do_GET(self) -> None:  # noqa: N802
            self._proxy()

        def do_POST(self) -> None:  # noqa: N802
            self._proxy()

        def log_message(self, format: str, *args: object) -> None:
            return

        def _proxy(self) -> None:
            if self.headers.get('Authorization', '') != auth_token:
                self.send_response(401)
                self.send_header('WWW-Authenticate', 'Basic realm="traderd"')
                self.end_headers()
                self.wfile.write(b'authentication required')
                return

            length = int(self.headers.get('Content-Length', '0') or '0')
            body = self.rfile.read(length) if length else None
            upstream_url = _upstream_url(target, self.path)
            headers = {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != 'host' and key.lower() != 'authorization'
            }
            headers['Host'] = urlsplit(target).netloc
            headers['X-Forwarded-For'] = self.client_address[0]
            headers['X-Forwarded-Proto'] = 'http'
            headers['X-Forwarded-Host'] = self.headers.get('Host', '')

            request = Request(upstream_url, data=body, headers=headers, method=self.command)
            try:
                with urlopen(request, timeout=30) as response:
                    payload = response.read()
                    self.send_response(response.status)
                    for key, value in response.headers.items():
                        if key.lower() in HOP_BY_HOP_HEADERS:
                            continue
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(payload)
            except HTTPError as exc:
                payload = exc.read()
                self.send_response(exc.code)
                for key, value in exc.headers.items():
                    if key.lower() in HOP_BY_HOP_HEADERS:
                        continue
                    self.send_header(key, value)
                self.end_headers()
                if payload:
                    self.wfile.write(payload)
            except (URLError, OSError) as exc:
                self.send_response(502)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(exc)}).encode('utf-8'))

    httpd = ThreadingHTTPServer((bind_host, bind_port), Handler)
    print(f'traderd dashboard proxy listening on http://{bind_host}:{bind_port} -> {target}', flush=True)
    httpd.serve_forever()
    return 0


def _upstream_url(base: str, request_path: str) -> str:
    split = urlsplit(base)
    request_split = urlsplit(request_path)
    path = request_split.path or '/'
    query = request_split.query
    return urlunsplit((split.scheme, split.netloc, path, query, ''))


if __name__ == '__main__':
    raise SystemExit(main())
