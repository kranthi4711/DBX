from dataclasses import dataclass, field
from typing import Any, Dict, List

@dataclass
class Source:
    alias: str
    full_name: str

    def to_dict(self) -> Dict[str, Any]:
        return {"alias": self.alias, "full_name": self.full_name}

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

    # logical target (client can type schema)
    output_catalog: str = ""
    output_schema: str = ""
    output_table: str = ""

    def output_fullname(self) -> str:
        if self.output_catalog and self.output_schema and self.output_table:
            return f"{self.output_catalog}.{self.output_schema}.{self.output_table}"
        return ""

    def final_output_alias(self) -> str:
        if not self.steps:
            return ""
        return self.steps[-1].output_alias

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "output_catalog": self.output_catalog,
            "output_schema": self.output_schema,
            "output_table": self.output_table,
            "steps": [s.to_dict() for s in self.steps],
        }
