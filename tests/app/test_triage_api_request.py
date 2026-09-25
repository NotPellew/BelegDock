import importlib.util
import json
from pathlib import Path
import sys


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "publish_triage.py"
SPEC = importlib.util.spec_from_file_location("belegdock_publish_triage_api", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return b"{}"


class Opener:
    request = None

    def open(self, request, timeout):
        self.request = request
        assert timeout == 20
        return Response()


def test_triage_write_sends_json_content_type() -> None:
    api = MODULE.GitHubApi("synthetic-test-token")
    opener = Opener()
    api.opener = opener
    api("POST", "/repos/NotPellew/BelegDock/labels", {"name": "triage:ready"})

    assert opener.request is not None
    assert opener.request.get_header("Content-type") == "application/json"
    assert json.loads(opener.request.data) == {"name": "triage:ready"}
