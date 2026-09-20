import base64
import binascii
import hashlib
import time
from collections.abc import Mapping
from pathlib import PurePath
from typing import Any
from urllib.parse import quote

from .workflow import DocumentRejected

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

    def labels(self) -> list[str]:
        labels = self.service.users().labels().list(userId="me").execute().get("labels", [])
        return [item["name"] for item in labels if isinstance(item, Mapping) and isinstance(item.get("name"), str)]

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
    _TYPES = "purchaseinvoice,purchasecreditnote,salesinvoice,salescreditnote"
    _MAX_GET_ATTEMPTS = 5
    _MIN_GET_INTERVAL = 0.5
    def __init__(self, client: Any):
        self.client = client
        self._last_get = 0.0

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
        if response.status_code in {400, 406}:
            raise DocumentRejected(response.status_code)
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

    def inventory(self, include_archived: bool = False, expected_organization_id: str | None = None) -> dict[str, Any]:
        organization = self._get("https://api.lexware.io/v1/profile")
        if organization.status_code != 200:
            raise RuntimeError("Lexware organization lookup failed")
        organization_data = organization.json()
        organization_id = organization_data.get("organizationId") if isinstance(organization_data, dict) else None
        if not isinstance(organization_id, str) or not organization_id:
            raise ValueError("Lexware organization response is invalid")
        if expected_organization_id is not None and organization_id != expected_organization_id:
            raise RuntimeError("Lexware organization does not match this state directory")
        files_by_id: dict[str, dict[str, Any]] = {}
        archived_states = ("false", "true") if include_archived else ("false",)
        for archived in archived_states:
            page = 0
            while True:
                response = self._get(
                    "https://api.lexware.io/v1/voucherlist",
                    params={"voucherType": self._TYPES, "voucherStatus": "any", "archived": archived, "page": page},
                )
                if response.status_code != 200:
                    raise RuntimeError("Lexware file inventory failed")
                body = response.json()
                if not isinstance(body, dict) or not isinstance(body.get("content"), list):
                    raise ValueError("Lexware file inventory response is invalid")
                last, number, total_pages = body.get("last"), body.get("number"), body.get("totalPages")
                empty_inventory = total_pages == 0 and page == 0 and not body["content"]
                if (
                    not isinstance(last, bool)
                    or not isinstance(number, int)
                    or number != page
                    or not isinstance(total_pages, int)
                    or total_pages < 0
                    or (not empty_inventory and (total_pages < 1 or page >= total_pages))
                    or (empty_inventory and not last)
                    or (not empty_inventory and last != (page == total_pages - 1))
                ):
                    raise ValueError("Lexware file inventory pagination is invalid")
                for item in body["content"]:
                    if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                        raise ValueError("Lexware voucher inventory entry is invalid")
                    detail = self._get(f"https://api.lexware.io/v1/vouchers/{quote(item['id'], safe='')}")
                    if detail.status_code != 200:
                        raise RuntimeError("Lexware voucher lookup failed")
                    voucher = detail.json()
                    if not isinstance(voucher, dict) or voucher.get("id") != item["id"] or not isinstance(voucher.get("files"), list):
                        raise ValueError("Lexware voucher response is invalid")
                    for file_item in voucher["files"]:
                        file_id = file_item if isinstance(file_item, str) else file_item.get("id") if isinstance(file_item, dict) else None
                        if not isinstance(file_id, str) or not file_id:
                            raise ValueError("Lexware voucher file reference is invalid")
                        entry = {"id": file_id, "voucherId": item["id"], "version": voucher.get("updatedDate"), "archived": archived == "true"}
                        previous = files_by_id.get(file_id)
                        if previous is not None and previous["voucherId"] != entry["voucherId"]:
                            raise ValueError("Lexware file is linked to conflicting vouchers")
                        if previous is None:
                            files_by_id[file_id] = entry
                        else:
                            previous["archived"] = bool(previous["archived"] or entry["archived"])
                if last:
                    break
                page += 1
        return {"organizationId": organization_id, "files": list(files_by_id.values())}

    def hash_file(self, file_id: str) -> str:
        if not isinstance(file_id, str) or not file_id:
            raise ValueError("remote file ID is invalid")
        data = self._download_file(file_id)
        return hashlib.sha256(data).hexdigest()

    def _get(self, url: str, **kwargs: Any) -> Any:
        for attempt in range(self._MAX_GET_ATTEMPTS):
            self._pace()
            response = self.client.get(url, timeout=30, **kwargs)
            if response.status_code != 429:
                return response
            if attempt + 1 == self._MAX_GET_ATTEMPTS:
                raise RuntimeError("Lexware request rate limited")
            self._retry_delay(response, attempt)
        raise RuntimeError("Lexware request failed")

    def _download_file(self, file_id: str) -> bytes:
        for attempt in range(self._MAX_GET_ATTEMPTS):
            self._pace()
            with self.client.stream("GET", f"https://api.lexware.io/v1/files/{quote(file_id, safe='')}", headers={"Accept": "*/*"}, timeout=30) as response:
                if response.status_code == 429:
                    if attempt + 1 == self._MAX_GET_ATTEMPTS:
                        raise RuntimeError("Lexware request rate limited")
                    self._retry_delay(response, attempt)
                    continue
                if response.status_code != 200:
                    raise RuntimeError("Lexware file verification failed")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes(chunk_size=65536):
                    total += len(chunk)
                    if total > MAX_FILE_SIZE:
                        raise ValueError("remote file exceeds the 5,000,000 byte limit")
                    chunks.append(chunk)
                return b"".join(chunks)
        raise RuntimeError("Lexware request failed")

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_get
        if elapsed < self._MIN_GET_INTERVAL:
            time.sleep(self._MIN_GET_INTERVAL - elapsed)
        self._last_get = time.monotonic()

    @staticmethod
    def _retry_delay(response: Any, attempt: int) -> None:
        try:
            delay = min(float(response.headers.get("Retry-After", "")), 1.0)
        except (TypeError, ValueError):
            delay = min(0.1 * (2**attempt), 1.0)
        time.sleep(max(delay, 0.001))

    def verify_existing(self, file_id: str, voucher_id: str) -> bytes:
        if not isinstance(file_id, str) or not file_id or not isinstance(voucher_id, str) or not voucher_id:
            raise ValueError("remote IDs are invalid")
        file_data = self._download_file(file_id)
        voucher_response = self._get(f"https://api.lexware.io/v1/vouchers/{quote(voucher_id, safe='')}")
        if voucher_response.status_code != 200:
            raise RuntimeError("Lexware voucher verification failed")
        voucher = voucher_response.json()
        if (
            not isinstance(voucher, dict)
            or voucher.get("id") != voucher_id
            or not self._voucher_references_file(voucher.get("files"), file_id)
        ):
            raise RuntimeError("Lexware voucher does not reference the file")
        return file_data

    @staticmethod
    def _voucher_references_file(files: Any, file_id: str) -> bool:
        if not isinstance(files, list):
            return False
        for item in files:
            if item == file_id:
                return True
            if isinstance(item, Mapping) and (item.get("id") == file_id or item.get("fileId") == file_id):
                return True
        return False
