"""Asks OPA one rule with one input: `opa eval`, a subprocess, no server and no network (V0666 layer C).

The verifier is a batch that wakes on a cadence, so it carries the policies and the opa binary and starts nothing that listens. A
rule OPA does not define, or an answer that is not a boolean, is an EvaluationError (an error of the run, counted apart from a
violation): the verifier never reads "undefined" as a pass.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List


class EvaluationError(Exception):
    pass


class OpaEvaluator:
    def __init__(self, binary: str, policy_dirs: List[str], timeout: float = 30.0) -> None:
        if not (binary and os.path.isfile(binary) and os.access(binary, os.X_OK)):
            raise EvaluationError("the opa binary is not there or not executable")
        for d in policy_dirs:
            if not os.path.isdir(d):
                raise EvaluationError(f"a policy directory is not there: {os.path.basename(d.rstrip('/'))}")
        self.binary, self.dirs, self.timeout = binary, list(policy_dirs), timeout

    async def decide(self, rego: str, data: Dict[str, Any]) -> bool:
        query = "data." + rego.replace("/", ".")
        cmd = [self.binary, "eval", "--format", "json", "--stdin-input", "--strict-builtin-errors=false"]
        for d in self.dirs:
            cmd += ["--data", d]
        cmd.append(query)
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.PIPE)
            out, err = await asyncio.wait_for(proc.communicate(json.dumps(data, default=str).encode()), self.timeout)
        except asyncio.TimeoutError:
            raise EvaluationError(f"{rego}: opa did not answer in {self.timeout:g}s") from None
        except OSError as exc:
            raise EvaluationError(f"{rego}: opa could not start ({type(exc).__name__})") from None
        if proc.returncode != 0:
            raise EvaluationError(f"{rego}: opa exited {proc.returncode}: {err.decode(errors='replace')[:200]}")
        try:
            result = json.loads(out.decode())["result"][0]["expressions"][0]["value"]
        except (KeyError, IndexError, ValueError):
            raise EvaluationError(f"{rego}: the rule is not defined in the loaded policies") from None
        if not isinstance(result, bool):
            raise EvaluationError(f"{rego}: the answer is not a boolean")
        return result
