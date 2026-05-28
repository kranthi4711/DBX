from dataclasses import dataclass, field
from typing import Any, Dict, List

@dataclass
class Source:
    alias: str
    full_name: str

    def to_dict(self) -> Dict[str, Any]:
        return {"alias": self.alias, "full_name": self.full_name}

@dataclass
class OutputTarget:
    from_alias: str
    catalog: str
    schema: str
    table: str
    mode: str = "overwrite"

    def full_name(self) -> str:
        if self.catalog and self.schema and self.table:
            return f"{self.catalog}.{self.schema}.{self.table}"
        return ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_alias": self.from_alias,
            "catalog": self.catalog,
            "schema": self.schema,
            "table": self.table,
            "mode": self.mode,
        }

@dataclass
class Step:
    input1: str
    input2: str = ""
    operation: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    output_alias: str = ""
    actions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input1": self.input1,
            "input2": self.input2,
            "operation": self.operation,
            "params": self.params,
            "output_alias": self.output_alias,
            "actions": self.actions,
        }

@dataclass
class Pipeline:
    name: str
    description: str = ""
    steps: List[Step] = field(default_factory=list)
    outputs: List[OutputTarget] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "outputs": [o.to_dict() for o in self.outputs],
        }
