"""One run of the verifier: read, build, ask, count, record (V0666 layer C). It detects; it never blocks and never writes to a
service: its only outputs are the metrics text, a findings file of its own, and the exit of the process."""
from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import hashlib
import inspect
import json
import logging
import pathlib
import time
from typing import Any, Dict, List, Optional

from . import evaluator as _ev
from .facts import Sources, Unmeasured
from .rules import RULES

log = logging.getLogger("opa_verifier")


class Recorder:
    """Appends each violation to a file of its own (JSON lines): when, what, the input the rule saw. One line per (rule, subject,
    input) until the violation clears and comes back."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = pathlib.Path(path)
        self._seen: set = set()          # violations recorded and not yet cleared
        self._open: set = set()          # violations of the run in progress

    def record(self, run_at: dt.datetime, rule: str, subject: str, severity: str, data: Dict[str, Any]) -> bool:
        key = hashlib.sha256(json.dumps([rule, subject, data], sort_keys=True, default=str).encode()).hexdigest()
        self._open.add(key)
        if key in self._seen:
            return False
        self._seen.add(key)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps({"at": run_at.isoformat(), "rule": rule, "subject": subject, "severity": severity,
                                "input": data}, sort_keys=True, default=str) + "\n")
        return True

    def end_run(self) -> None:
        self._seen &= self._open         # a violation that cleared is recorded again if it returns
        self._open = set()


_METRICS = (("opa_verifier_violations", "Subjects a rule judged and found in violation, this run", "violations"),
            ("opa_verifier_subjects", "Subjects a rule judged this run (0 means it judged nothing)", "subjects"),
            ("opa_verifier_unmeasured", "Facts a rule could not read this run (not a pass, not a violation)", "unmeasured"),
            ("opa_verifier_rule_errors", "Rules whose evaluation or reading failed this run", "errors"))


@dataclasses.dataclass
class RunResult:
    at: dt.datetime
    seconds: float = 0.0
    violations: Dict[str, int] = dataclasses.field(default_factory=dict)
    subjects: Dict[str, int] = dataclasses.field(default_factory=dict)
    unmeasured: Dict[str, int] = dataclasses.field(default_factory=dict)
    errors: Dict[str, int] = dataclasses.field(default_factory=dict)
    findings: List[Dict[str, Any]] = dataclasses.field(default_factory=list)

    @classmethod
    def empty(cls) -> "RunResult":
        z = {r: 0 for r in RULES}
        return cls(at=dt.datetime.fromtimestamp(0, dt.timezone.utc), violations=dict(z), subjects=dict(z), unmeasured=dict(z),
                   errors=dict(z))

    def metrics_text(self) -> str:
        lines: List[str] = []
        for name, help_, attr in _METRICS:
            lines += [f"# HELP {name} {help_}", f"# TYPE {name} gauge"]
            lines += [f'{name}{{rule="{r}"}} {getattr(self, attr)[r]}' for r in RULES]
        lines += ["# HELP opa_verifier_last_run_unixtime When the last run started", "# TYPE opa_verifier_last_run_unixtime gauge",
                  f"opa_verifier_last_run_unixtime {int(self.at.timestamp())}",
                  "# HELP opa_verifier_run_seconds How long the last run took", "# TYPE opa_verifier_run_seconds gauge",
                  f"opa_verifier_run_seconds {self.seconds:.3f}"]
        return "\n".join(lines) + "\n"


async def _subjects(sources: Sources, rule: str, node: str) -> List[Any]:
    got = sources.subjects(rule, node)
    return list(await got) if inspect.isawaitable(got) else list(got)


async def run_once(sources: Sources, opa: Any, *, recorder: Optional[Recorder] = None) -> RunResult:
    started = time.monotonic()
    at = sources.now()
    res = RunResult.empty()
    res.at = at
    for rule in RULES.values():
        for node in sources.nodes():
            try:
                subjects = await _subjects(sources, rule.name, node)
            except Unmeasured as exc:
                res.unmeasured[rule.name] += 1
                log.warning("unmeasured %s on %s: %s", rule.name, node, exc)
                continue
            except Exception as exc:  # noqa: BLE001: one rule's reader never stops the others
                res.errors[rule.name] += 1
                log.error("%s on %s: the reader failed (%s)", rule.name, node, type(exc).__name__)
                continue
            for subject, facts in subjects:
                try:
                    data = rule.build(facts)
                    ok = await opa.decide(rule.rego, data)
                except _ev.EvaluationError as exc:
                    res.errors[rule.name] += 1
                    log.error("%s on %s: %s", rule.name, subject, exc)
                    continue
                except Exception as exc:  # noqa: BLE001
                    res.errors[rule.name] += 1
                    log.error("%s on %s: the builder or the evaluator failed (%s)", rule.name, subject, type(exc).__name__)
                    continue
                res.subjects[rule.name] += 1
                if not ok:
                    res.violations[rule.name] += 1
                    res.findings.append({"rule": rule.name, "subject": subject, "node": node, "input": data})
                    if recorder is not None:
                        recorder.record(at, rule.name, subject, rule.severity, data)
    if recorder is not None:
        recorder.end_run()
    res.seconds = time.monotonic() - started
    return res
