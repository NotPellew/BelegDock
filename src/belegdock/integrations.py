import base64
import binascii
from collections.abc import Mapping
from pathlib import PurePath
from typing import Any


MAX_FILE_SIZE = 5_000_000
_MIME_TYPES = {".pdf": "application/pdf", ".xml": "application/xml"}


def _decode_base64url(value: str) -> bytes:
    if not isinstance(value, str) or len(value) > 4 * ((MAX_FILE_SIZE + 2) // 3):
        raise ValueError("attachment data is invalid")
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.b64decode(padded, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("attachment data is invalid") from error


class GmailAdapter:
    def __init__(self, service: Any):
        self.service = service

    def candidates(self, label_name: str) -> list[dict[str, Any]]:
        labels = self.service.users().labels().list(userId="me").execute().get("labels", [])
        label_id = next((item.get("id") for item in labels if item.get("name") == label_name), None)
        if not label_id:
            raise ValueError("Gmail label was not found")

        candidates: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            parameters: dict[str, Any] = {"userId": "me", "labelIds": [label_id]}
            if page_token:
                parameters["pageToken"] = page_token
            page = self.service.users().messages().list(**parameters).execute()
            for summary in page.get("messages", []):
                message_id = summary.get("id")
                if not message_id:
                    continue
                message = self.service.users().messages().get(
                    userId="me", id=message_id, format="full"
                ).execute()
                self._collect_parts(message_id, message.get("payload", {}), candidates)
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        return candidates

    def _collect_parts(
        self, message_id: str, part: Mapping[str, Any], candidates: list[dict[str, Any]]
    ) -> None:
        filename = part.get("filename")
        suffix = PurePath(filename).suffix.lower() if isinstance(filename, str) else ""
        body = part.get("body") or {}
        if isinstance(filename, str) and suffix in _MIME_TYPES:
            part_id = part.get("partId")
            attachment_id = body.get("attachmentId")
            inline_data = body.get("data")
            declared_size = body.get("size")
            if not isinstance(part_id, str) or not part_id or (attachment_id is None and inline_data is None):
                raise ValueError("Gmail document part is malformed")
            if attachment_id:
                size = declared_size
            elif inline_data is not None:
                decoded = _decode_base64url(inline_data)
                size = len(decoded) if declared_size is None else declared_size
            else:
                size = declared_size
            if isinstance(size, int) and 0 <= size <= MAX_FILE_SIZE:
                candidate: dict[str, Any] = {
                    "id": f"{message_id}:{part_id}",
                    "message_id": message_id,
                    "part_id": part_id,
                    "filename": filename,
                    "size": size,
                }
                if attachment_id:
                    candidate["attachment_id"] = attachment_id
                elif inline_data is not None:
                    candidate["inline_data"] = inline_data
                candidates.append(candidate)
        for child in part.get("parts", []) or []:
            if isinstance(child, Mapping):
                self._collect_parts(message_id, child, candidates)

    def fetch(self, candidate: Mapping[str, Any]) -> bytes:
        expected_size = candidate.get("size")
        if not isinstance(expected_size, int) or expected_size < 0 or expected_size > MAX_FILE_SIZE:
            raise ValueError("attachment size is invalid")
        inline_data = candidate.get("inline_data")
        if inline_data is not None:
            data = _decode_base64url(inline_data)
        else:
            message_id = candidate.get("message_id")
            attachment_id = candidate.get("attachment_id")
            if not isinstance(message_id, str) or not isinstance(attachment_id, str):
                raise ValueError("attachment reference is invalid")
            body = self.service.users().messages().attachments().get(
                userId="me", messageId=message_id, id=attachment_id
            ).execute()
            data = _decode_base64url(body.get("data", ""))
            remote_size = body.get("size")
            if remote_size is not None and remote_size != len(data):
                raise ValueError("attachment size is invalid")
        if len(data) != expected_size or len(data) > MAX_FILE_SIZE:
            raise ValueError("attachment size is invalid")
        return data


class LexwareAdapter:
    def __init__(self, client: Any):
        self.client = client

    def upload(self, data: bytes, filename: str) -> dict[str, Any]:
        if not isinstance(data, bytes) or len(data) > MAX_FILE_SIZE:
            raise ValueError("file size is invalid")
        suffix = PurePath(filename).suffix.lower()
        mime_type = _MIME_TYPES.get(suffix)
        if mime_type is None:
            raise ValueError("file format is unsupported")
        response = self.client.post(
            "https://api.lexware.io/v1/files",
            data={"type": "voucher"},
            files={"file": (filename, data, mime_type)},
            timeout=30,
        )
        if response.status_code != 202:
            raise RuntimeError("Lexware upload failed")
        result = response.json()
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("id"), str)
            or not result["id"]
            or not isinstance(result.get("voucherId"), str)
            or not result["voucherId"]
        ):
            raise ValueError("Lexware upload response is invalid")
        return {"id": result["id"], "voucherId": result["voucherId"]}
