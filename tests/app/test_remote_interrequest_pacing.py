from unittest.mock import patch

import httpx
from belegdock.integrations import LexwareAdapter


def test_interrequest_metadata_pacing_is_at_least_half_second():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/profile":
            return httpx.Response(200, json={"organizationId": "org-1"}, request=request)
        return httpx.Response(200, json={"content": [], "last": True, "number": 0, "totalPages": 0}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with patch("belegdock.integrations.time.monotonic", side_effect=[10.0, 10.0, 10.0, 10.0]):
        with patch("belegdock.integrations.time.sleep") as sleep:
            LexwareAdapter(client).inventory()
    client.close()
    assert any(call.args[0] >= 0.5 for call in sleep.call_args_list)
