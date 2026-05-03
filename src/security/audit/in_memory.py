class InMemoryAuditLog:
    def __init__(self):
        self.events = []

    def append(self, event: dict) -> None:
        self.events.append(event)

    def list_events(self) -> list[dict]:
        return list(self.events)