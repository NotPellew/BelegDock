class ManualOperationDispatcher:
    def __init__(self):
        self._operations = []

    def __call__(self, operation, completed):
        self._operations.append((operation, completed))

    @property
    def pending_count(self):
        return len(self._operations)

    def complete_next(self):
        operation, completed = self._operations.pop(0)
        try:
            result = operation()
        except Exception as error:
            completed(None, error)
        else:
            completed(result, None)
