def error_detail(error_code: str, message: str, audit_event: dict | None = None) -> dict:
    return {'error_code': error_code, 'message': message, 'audit_event': audit_event or {}}
