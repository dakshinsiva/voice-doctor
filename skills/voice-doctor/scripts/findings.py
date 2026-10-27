"""Finding and Audit types shared by the config and code checks."""

from __future__ import annotations

from dataclasses import dataclass, field

from lint_prompt import SEVERITY_COST


@dataclass
class Finding:
    rule: str
    severity: str
    field: str
    current: object
    suggested: str
    why: str
    file: str | None = None  # set by the code checks (LiveKit, Pipecat)
    line: int | None = None


@dataclass
class Audit:
    findings: list[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def add(self, rule, severity, field_, current, suggested, why, file=None, line=None):
        self.findings.append(Finding(rule, severity, field_, current, suggested, why, file, line))

    @property
    def score(self) -> int:
        return max(0, 100 - sum(SEVERITY_COST[f.severity] for f in self.findings))
