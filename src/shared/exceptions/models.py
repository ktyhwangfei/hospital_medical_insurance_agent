class PermissionDeniedError(Exception):
    def __init__(self, message: str, audit_event: dict):
        super().__init__(message)
        self.audit_event = audit_event
