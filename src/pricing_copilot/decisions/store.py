from __future__ import annotations

import sqlite3
from pathlib import Path

from pricing_copilot.contracts import AnalystDecision, Product, Region, Segment

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    record_id TEXT PRIMARY KEY,
    product TEXT NOT NULL,
    region TEXT NOT NULL,
    segment TEXT NOT NULL,
    decision TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    payload TEXT NOT NULL
)
"""


class DecisionStore:
    """Local SQLite persistence for analyst decision records."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._connection.execute(_SCHEMA)
        self._connection.commit()

    @classmethod
    def from_path(cls, path: Path) -> "DecisionStore":
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path))
        return cls(connection)

    def save(self, decision: AnalystDecision) -> None:
        if decision.record_id is None:
            raise ValueError("Cannot save a decision without a record_id.")
        self._connection.execute(
            "INSERT OR REPLACE INTO decisions "
            "(record_id, product, region, segment, decision, decided_at, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                decision.record_id,
                decision.question.product.value,
                decision.question.region.value,
                decision.question.segment.value,
                decision.decision.value,
                decision.decided_at.isoformat(),
                decision.model_dump_json(),
            ),
        )
        self._connection.commit()

    def get(self, record_id: str) -> AnalystDecision | None:
        row = self._connection.execute(
            "SELECT payload FROM decisions WHERE record_id = ?", (record_id,)
        ).fetchone()
        if row is None:
            return None
        return AnalystDecision.model_validate_json(row[0])

    def list_for_question(
        self, product: Product, region: Region, segment: Segment
    ) -> list[AnalystDecision]:
        rows = self._connection.execute(
            "SELECT payload FROM decisions WHERE product = ? AND region = ? AND segment = ? "
            "ORDER BY decided_at DESC",
            (product.value, region.value, segment.value),
        ).fetchall()
        return [AnalystDecision.model_validate_json(row[0]) for row in rows]
