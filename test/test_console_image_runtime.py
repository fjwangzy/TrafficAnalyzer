"""Opt-in real-image regression for public files with private legacy mounts/umask."""
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

import pytest

pytestmark = pytest.mark.skipif(os.getenv('RUN_CONSOLE_IMAGE_TEST') != '1', reason='requires a built ARM64 Console image and Docker')


def test_console_serves_public_files_with_unreadable_legacy_html_and_private_umask():
    image = os.environ.get('CONSOLE_IMAGE_UNDER_TEST', 'traffic-analyzer-console:2026.10.18.4-arm64')
    command = ['docker', 'run', '-d', '--rm', '--add-host', 'platform:127.0.0.1',
               '-p', '127.0.0.1::8080', '--entrypoint', 'sh', image, '-c',
               'umask 077; mkdir -p /usr/share/nginx/html; chmod 000 /usr/share/nginx/html; '
               'exec /docker-entrypoint.sh nginx -g "daemon off;"']
    container = subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()
    try:
        port = subprocess.run(['docker', 'port', container, '8080/tcp'], capture_output=True, text=True, check=True).stdout.strip().split(':')[-1]
        base = 'http://127.0.0.1:' + port
        deadline = time.monotonic() + 10
        while True:
            try:
                response = urllib.request.urlopen(base + '/index.html', timeout=2)
                break
            except urllib.error.HTTPError as error:
                pytest.fail(f'index.html returned {error.code}; public files must be readable by the Nginx worker')
            except (urllib.error.URLError, ConnectionResetError):
                if time.monotonic() >= deadline:
                    pytest.fail('Console did not become reachable')
                time.sleep(0.1)
        html = response.read().decode()
        response.close()
        assert 'type="module"' in html
        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+\.(?:js|css))"', html)
        assert assets
        for path in ['/', '/login', '/runtime-config.js', *assets]:
            with urllib.request.urlopen(base + path, timeout=3) as result:
                assert result.status == 200
                assert result.read()
        mode = subprocess.run(['docker', 'exec', container, 'stat', '-c', '%a', '/opt/traffic-console/html/runtime-config.js'], capture_output=True, text=True, check=True).stdout.strip()
        assert mode == '644'
        legacy = subprocess.run(['docker', 'exec', container, 'stat', '-c', '%a', '/usr/share/nginx/html'], capture_output=True, text=True, check=True).stdout.strip()
        assert int(legacy) == 0  # The fix must not chmod a legacy host-mount path.
    finally:
        subprocess.run(['docker', 'rm', '-f', container], capture_output=True, check=True)
