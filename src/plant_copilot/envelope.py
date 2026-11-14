import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field


class Coverage(BaseModel):
    expected: int = 0
    observed: int = 0
    missing_ranges: list[str] = Field(default_factory=list)


class MetricResult(BaseModel):
    status: Literal["ok", "incomplete", "insufficient_data", "ambiguous", "error"]
    value: Any = None
    display: str = ""
    metric: str
    sql: str = ""
    logic: str = ""
    params: dict = Field(default_factory=dict)
    rows_used: int = 0
    as_of: str = ""
    coverage: Coverage = Field(default_factory=Coverage)
    caveats: list[str] = Field(default_factory=list)
    sensitivity: list[dict] = Field(default_factory=list)
    needed_data: str = ""
    details: list[dict] = Field(default_factory=list)
    result_hash: str = ""

    def seal(self) -> "MetricResult":
        payload = self.model_dump(exclude={"result_hash"})
        text = json.dumps(payload, sort_keys=True, default=str)
        self.result_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return self
