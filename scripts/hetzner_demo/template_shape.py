"""§MTLSHOPS T2 (2026-09-15, with agentvault2-85): a resume runs TODAY's driver and provisioner on a stack an EARLIER
template rendered. After the T2 flip that is the T2 driver and provisioner on a frame built before T2 (lantern: no kit TLS,
no sockets, no edge), which a resume would half-convert: its kit gates run on every resume and its spire step registers
T2's entries. The runner's resume and the driver's resume branch both ask this module first and refuse when the stack
and today's template differ in generation or in service set.

The generation is the compose template's `# frame-template-generation: <token>` line (none = "unmarked"). Bump it
whenever a template change makes resuming an older stack unsafe. The service set is the second, automatic witness: a
service the template gained or lost is a different frame, even when nobody bumped the line. A side that cannot be read
is a reason, never a pass.

tools/frame-runner/frame_runner.py loads this file from beside the driver it launches; the contract's R31 pins both calls.
"""
from __future__ import annotations

import os
import re

COMPOSE_NAME = "docker-compose.frame-test.yml"
GENERATION_RE = re.compile(r"(?m)^# frame-template-generation: (\S+)[ \t]*$")
_SERVICE_RE = re.compile(r"^  ([^\s#][^:\s]*):[ \t]*$")


def compose_generation(text: str) -> str:
    found = sorted(set(GENERATION_RE.findall(text)))
    if not found:
        return "unmarked"
    return found[0] if len(found) == 1 else "ambiguous (" + ", ".join(found) + ")"


def compose_services(text: str) -> set:
    """The keys of the top-level `services:` mapping (two-space indent); volumes and networks are not services."""
    out, inside = set(), False
    for line in text.splitlines():
        if re.match(r"^services:[ \t]*$", line):
            inside = True
            continue
        if inside and re.match(r"^[^\s#]", line):
            inside = False
        if inside:
            m = _SERVICE_RE.match(line)
            if m:
                out.add(m.group(1))
    return out


def _names(items, cap=8) -> str:
    items = sorted(items)
    return ", ".join(items[:cap]) + (f" (+{len(items) - cap} more)" if len(items) > cap else "")


def generation_mismatch(stack_compose: str, template: str) -> list:
    have, want = compose_generation(stack_compose), compose_generation(template)
    if have == want:
        return []
    return [f"template generation: the stack was rendered from {have}, today's template is {want}"]


def service_set_mismatch(stack_compose: str, template: str, name: str) -> list:
    stack = compose_services(stack_compose)
    tmpl = {s.replace("{{REGISTRY_NAME}}", name) for s in compose_services(template)}
    why = []
    if tmpl - stack:
        why.append("services today's template renders and the stack lacks: " + _names(tmpl - stack))
    if stack - tmpl:
        why.append("services the stack runs and today's template no longer renders: " + _names(stack - tmpl))
    return why


def template_shape_mismatch(stack_compose: str, template: str, name: str) -> list:
    """Why a stack rendered as `stack_compose` is not the frame `template` renders for `name`; [] = the same shape."""
    return generation_mismatch(stack_compose, template) + service_set_mismatch(stack_compose, template, name)


def stack_template_mismatch(stack_dir: str, template_path: str, name: str) -> list:
    """The same question over the files a resume would use."""
    try:
        with open(os.path.join(stack_dir, COMPOSE_NAME), encoding="utf-8") as f:
            stack = f.read()
    except OSError as exc:
        return [f"the stack's {COMPOSE_NAME} cannot be read ({type(exc).__name__})"]
    try:
        with open(template_path, encoding="utf-8") as f:
            template = f.read()
    except OSError as exc:
        return [f"today's compose template cannot be read ({type(exc).__name__})"]
    return template_shape_mismatch(stack, template, name)


def refusal_sentence(name: str, why: list, template: str = "") -> str:
    want = compose_generation(template) if template else "today's"
    onto = f"the {want} template" if template else "today's template"
    return (f"{name} cannot be resumed: " + "; ".join(why) + ". A resume runs today's driver and provisioner on the "
            f"frame's stack, which would half-convert a frame another template rendered. The way out is to re-render "
            f"{name} onto {onto} first, which on a live frame is a retrofit window and needs the Commander's word "
            f"(for a frame built before mtlshops-t2 that is §MTLSHOPS T6), or to tear it down and stand it up again.")
