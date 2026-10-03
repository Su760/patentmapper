"""In-memory query fixtures for isolated HTTP security regressions."""
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

class MemoryDB:
    """Model the three job tables and unique search_results.search_id constraint."""
    def __init__(self):
        self.rows = {"searches": [], "search_results": [], "patents": []}
        self.writes = []
        self.fail_tables = set()
        self.auth = SimpleNamespace(get_user=AsyncMock(return_value=SimpleNamespace(
            user=SimpleNamespace(id="00000000-0000-0000-0000-000000000001")
        )))

    def table(self, name):
        return MemoryQuery(self, name)

    def rpc(self, _name, _params):
        return SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(data="allowed")))


class MemoryQuery:
    def __init__(self, db, name):
        self.db, self.name = db, name
        self.operation, self.payload, self.filters = "select", None, {}
        self.one = False

    def insert(self, payload):
        self.operation, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.operation, self.payload = "update", payload
        return self

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def single(self):
        self.one = True
        return self

    def limit(self, _count):
        return self

    async def execute(self):
        if self.name in self.db.fail_tables:
            raise RuntimeError("synthetic database outage")
        rows = self.db.rows[self.name]
        if self.operation == "insert":
            incoming = self.payload if isinstance(self.payload, list) else [self.payload]
            if self.name == "search_results" and any(
                old["search_id"] == new["search_id"] for old in rows for new in incoming
            ):
                raise RuntimeError("duplicate search result")
            rows.extend(copy.deepcopy(incoming))
        elif self.operation == "update":
            for row in rows:
                if all(row.get(k) == v for k, v in self.filters.items()):
                    row.update(copy.deepcopy(self.payload))
        if self.operation != "select":
            self.db.writes.append((self.name, self.operation, copy.deepcopy(self.payload)))
        selected = [r for r in rows if all(r.get(k) == v for k, v in self.filters.items())]
        return SimpleNamespace(data=selected[0] if self.one and selected else selected)
