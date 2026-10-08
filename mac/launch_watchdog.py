"""Core macOS app launcher; the Finder app invokes this file directly."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request


def main():
    repo, menu_binary = map(Path, sys.argv[1:3])
    backend = None
    log_path = Path(tempfile.gettempdir()) / 'llm-watchdog-app.log'
    def ready():
        try:
            with urllib.request.urlopen('http://127.0.0.1:8080/api/status', timeout=2) as response:
                data = json.load(response)
                return 'models' in data and 'status' in data
        except (OSError, ValueError):
            return False
    with log_path.open('a') as log:
        if not ready():
            backend = subprocess.Popen([sys.executable, '-m', 'watchdog.llm_watchdog'],
                                       cwd=repo, stdout=log, stderr=log, start_new_session=True)
            deadline = time.monotonic() + 15
            while not ready():
                if backend.poll() is not None or time.monotonic() > deadline:
                    if backend.poll() is None:
                        backend.terminate()
                    raise RuntimeError(f'LLM watchdog failed to start; see {log_path}')
                time.sleep(0.2)
        subprocess.run([str(menu_binary)], check=True, stdout=log, stderr=log)


if __name__ == '__main__':
    main()
