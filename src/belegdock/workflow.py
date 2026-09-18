from collections.abc import Callable
from pathlib import Path


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def stage(self, account, message_id, part_id, filename, data: bytes):
        raise NotImplementedError("workflow staging is not implemented")

    def list_documents(self):
        raise NotImplementedError("workflow listing is not implemented")

    def occurrences(self, digest):
        raise NotImplementedError("workflow occurrences are not implemented")

    def upload(self, digest, uploader: Callable[[bytes, str], dict]):
        raise NotImplementedError("workflow upload is not implemented")
