class GmailAdapter:
    def __init__(self, service):
        self.service = service

    def candidates(self, label_name):
        return []

    def fetch(self, candidate):
        return b""


class LexwareAdapter:
    def __init__(self, client):
        self.client = client

    def upload(self, data, filename):
        return {}
