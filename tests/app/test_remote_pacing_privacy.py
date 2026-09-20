from unittest.mock import patch

import httpx

from belegdock.integrations import LexwareAdapter
from belegdock.workflow import Store


def test_metadata_gets_are_paced_for_provider_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/profile":
            return httpx.Response(200, json={"organizationId": "org-1"}, request=request)
        return httpx.Response(
            200,
            json={"content": [], "last": True, "number": 0, "totalPages": 0},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with patch("belegdock.integrations.time.monotonic", side_effect=[0.0, 0.0, 0.01, 0.01]):
        with patch("belegdock.integrations.time.sleep") as sleep:
            LexwareAdapter(client).inventory()
    client.close()
    assert any(call.args[0] >= 0.5 for call in sleep.call_args_list)


def test_refresh_failure_does_not_persist_remote_exception_text(tmp_path):
    store = Store(tmp_path)

    class Remote:
        def inventory(self, **kwargs):
            raise RuntimeError("private-sentinel")

    from belegdock import cli

    try:
        cli.refresh_remote_inventory(store, Remote())
    except RuntimeError:
        pass
    with store._connection() as connection:
        values = [row[0] for row in connection.execute("SELECT value FROM remote_state")]
    assert "private-sentinel" not in values
    assert any(value == "failed" for value in values)
