"""§MCPTEST30 (V0549) — the request headers a route refuses to go on without, read from its handler (helper, not a test file).

FastAPI validates a header the route DECLARES as required (`Header(...)`), and the request survey sees that answer. A
handler can also read a header itself and refuse without it:

    license_key = request.headers.get("X-Federation-License")
    if not license_key:
        raise HTTPException(status_code=401, detail="X-Federation-License header required")

and nothing in the route's signature says so. getCloudOperatorSelfLogs and cloudOperatorSelfRestart call two such routes
(a cloud operator's own licence, cloud_operators.py) and federationCliAudit a third (an optional `Header(None)` checked in
the body, federation_cli_audit.py); none of the three sends the header, so each answers 401 or 400 to every MCP caller.
Round 14 read the first as a refusal its contract accepted.

The rule, read from the source: walk the handler's top-level statements (and those of every dependency in the route's
tree) in order; a name bound to a header read (`<req>.headers.get("H"[, default])`, or a parameter whose default is
`Header(None, alias="H")`) takes the value it has when the header is ABSENT; an `if` whose test is then certainly true
and whose block raises HTTPException 400, 401 or 403 makes that header required. The walk stops at the first statement
that can return (the route may answer without the header past that point), so a header the handler only reads
optionally, or behind a branch, is never reported. Pure (ast only): importing this module patches nothing.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Any, Dict, List, Optional, Set, Tuple

REFUSALS = {400, 401, 403}
_STATUS_NAMES = {"HTTP_400_BAD_REQUEST": 400, "HTTP_401_UNAUTHORIZED": 401, "HTTP_403_FORBIDDEN": 403}
UNKNOWN = object()   # a value the walk cannot know from the source alone


def _header_read(node: ast.AST) -> Optional[Tuple[str, Any]]:
    """`<x>.headers.get("H"[, default])` -> (H, the value when H is absent); None for anything else."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"):
        return None
    owner = node.func.value
    if not (isinstance(owner, ast.Attribute) and owner.attr == "headers"):
        return None
    if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
        return None
    default: Any = None
    if len(node.args) > 1:
        default = node.args[1].value if isinstance(node.args[1], ast.Constant) else UNKNOWN
    for kw in node.keywords:
        if kw.arg == "default":
            default = kw.value.value if isinstance(kw.value, ast.Constant) else UNKNOWN
    return node.args[0].value, default


def _value(node: ast.AST, env: Dict[str, Any], seen: Set[str]) -> Any:
    """The expression's value with every header it reads ABSENT, Python's own short-circuit rules; UNKNOWN where the
    source alone cannot tell. `seen` collects the headers the expression reads (directly or through a bound name)."""
    read = _header_read(node)
    if read is not None:
        seen.add(read[0])
        return read[1]
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            hname, value = env[node.id]
            seen.add(hname)
            return value
        return UNKNOWN
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        v = _value(node.operand, env, seen)
        return UNKNOWN if v is UNKNOWN else (not v)
    if isinstance(node, ast.BoolOp):
        last: Any = UNKNOWN
        for operand in node.values:
            v = _value(operand, env, seen)
            if v is UNKNOWN:
                return UNKNOWN
            if isinstance(node.op, ast.And) and not v:
                return v
            if isinstance(node.op, ast.Or) and v:
                return v
            last = v
        return last
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        left = _value(node.left, env, seen)
        right = _value(node.comparators[0], env, seen)
        if left is UNKNOWN or right is UNKNOWN:
            return UNKNOWN
        op = node.ops[0]
        if isinstance(op, ast.Is):
            return left is right
        if isinstance(op, ast.IsNot):
            return left is not right
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
    return UNKNOWN


def _status(call: ast.Call) -> Optional[int]:
    vals = [kw.value for kw in call.keywords if kw.arg == "status_code"] or call.args[:1]
    for v in vals:
        if isinstance(v, ast.Constant) and isinstance(v.value, int):
            return v.value
        if isinstance(v, ast.Attribute) and v.attr in _STATUS_NAMES:
            return _STATUS_NAMES[v.attr]
    return None


def _refuses(block: List[ast.stmt]) -> Optional[int]:
    """The 400/401/403 a block raises as one of its own statements (HTTPException), else None."""
    for st in block:
        if isinstance(st, ast.Raise) and isinstance(st.exc, ast.Call):
            f = st.exc.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            code = _status(st.exc) if name == "HTTPException" else None
            if code in REFUSALS:
                return code
    return None


def _can_return(node: ast.AST) -> bool:
    """Whether a statement contains a `return` of the function itself (a nested def or lambda has its own)."""
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, ast.Return):
            return True
        for child in ast.iter_child_nodes(n):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                stack.append(child)
    return False


def _header_param(arg: ast.arg, default: Optional[ast.AST]) -> Optional[Tuple[str, Any]]:
    """A parameter whose default is `Header(<absent value>, alias=...)` -> (header name, absent value). A required
    `Header(...)` is FastAPI's to validate (the survey already sees that 422), so it is not returned here."""
    if not (isinstance(default, ast.Call) and getattr(default.func, "id", getattr(default.func, "attr", "")) == "Header"):
        return None
    absent: Any = None
    first = default.args[0] if default.args else next((kw.value for kw in default.keywords if kw.arg == "default"), None)
    if isinstance(first, ast.Constant):
        if first.value is Ellipsis:
            return None
        absent = first.value
    elif first is not None:
        return None
    alias = next((kw.value.value for kw in default.keywords
                  if kw.arg == "alias" and isinstance(kw.value, ast.Constant)), None)
    return (alias or arg.arg.replace("_", "-")), absent


def required_headers_in(func: ast.AST) -> List[Tuple[str, int]]:
    """(header, status) for each header the function refuses to go on without, per the rule in the module docstring."""
    if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    env: Dict[str, Tuple[str, Any]] = {}
    a = func.args
    positional = a.posonlyargs + a.args
    defaults: List[Optional[ast.AST]] = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
    for arg, default in list(zip(positional, defaults)) + list(zip(a.kwonlyargs, a.kw_defaults)):
        hp = _header_param(arg, default)
        if hp is not None:
            env[arg.arg] = hp
    found: List[Tuple[str, int]] = []
    for st in func.body:
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant):
            continue  # the docstring
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            seen: Set[str] = set()
            v = _value(st.value, env, seen)
            if seen and v is not UNKNOWN and len(seen) == 1:
                env[st.targets[0].id] = (next(iter(seen)), v)
            continue
        if isinstance(st, ast.If):
            seen = set()
            code = _refuses(st.body)
            if code is not None and _value(st.test, env, seen) is True and seen:
                found.extend((h, code) for h in sorted(seen) if h not in {f[0] for f in found})
                continue
        if _can_return(st):
            break
    return found


def _source_function(fn: Any) -> Optional[ast.AST]:
    try:
        src = textwrap.dedent(inspect.getsource(inspect.unwrap(fn)))
        tree = ast.parse(src)
    except (OSError, TypeError, SyntaxError, IndentationError):
        return None   # no source (a bytecode-only image, a builtin, a class instance): the walk reports nothing
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return None


_CACHE: Dict[int, List[Tuple[str, int]]] = {}


def function_required_headers(fn: Any) -> List[Tuple[str, int]]:
    key = id(fn)
    if key not in _CACHE:
        node = _source_function(fn) if (inspect.isfunction(fn) or inspect.ismethod(fn)) else None
        _CACHE[key] = required_headers_in(node) if node is not None else []
    return _CACHE[key]


def route_required_headers(route: Any) -> List[Tuple[str, int, str]]:
    """(header, status, where) for the route's handler and every function in its dependency tree."""
    out: List[Tuple[str, int, str]] = []
    fns: List[Any] = [getattr(route, "endpoint", None)]
    stack, seen = [getattr(route, "dependant", None)], set()
    while stack:
        d = stack.pop()
        if d is None or id(d) in seen:
            continue
        seen.add(id(d))
        fns.append(getattr(d, "call", None))
        stack.extend(getattr(d, "dependencies", None) or [])
    done: Set[int] = set()
    for fn in fns:
        if fn is None or id(fn) in done:
            continue
        done.add(id(fn))
        for h, code in function_required_headers(fn):
            out.append((h, code, f"{getattr(fn, '__module__', '?').rsplit('.', 1)[-1]}.{getattr(fn, '__name__', '?')}"))
    return out


# ── §MCPTEST30 (V0550): the keys a handler reads from an untyped dict body ──────────────────────────────────────────────
# A route whose body is `Dict[str, Any] = Body(...)` validates nothing, so FastAPI's own validation (and the survey's
# BODY_UNDECLARED) cannot see a key the tool sends and the handler never reads. testApiEndpoint sent {"endpoint_path"}
# to a handler reading endpoint_test.get("path", ""), so every call tested an empty path; generateTutorialProof sent
# {"tutorial_id"} to one reading circuit_id ("Unknown circuit: ." on every call; agentvault2-45 found it). The rule: every
# use of the body parameter in the handler is a read of a constant key (.get("k"[, d]), ["k"], "k" in body, .pop/
# .setdefault("k")); any other use (passed on, iterated, unpacked, aliased) makes the set unknowable and nothing is said.

def _body_param_reads(func: ast.AST, name: str) -> Optional[Set[str]]:
    reads: Set[str] = set()
    parents: Dict[int, ast.AST] = {}
    for node in ast.walk(func):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    for node in ast.walk(func):
        if not (isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load)):
            continue
        parent = parents.get(id(node))
        # body.get("k") / body.pop("k") / body.setdefault("k")
        if isinstance(parent, ast.Attribute) and parent.value is node and parent.attr in ("get", "pop", "setdefault"):
            call = parents.get(id(parent))
            if (isinstance(call, ast.Call) and call.func is parent and call.args
                    and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)):
                reads.add(call.args[0].value)
                continue
            return None
        # body["k"]
        if isinstance(parent, ast.Subscript) and parent.value is node:
            key = parent.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                reads.add(key.value)
                continue
            return None
        # "k" in body / "k" not in body
        if (isinstance(parent, ast.Compare) and node in parent.comparators and len(parent.ops) == 1
                and isinstance(parent.ops[0], (ast.In, ast.NotIn)) and isinstance(parent.left, ast.Constant)
                and isinstance(parent.left.value, str)):
            reads.add(parent.left.value)
            continue
        return None   # any other use: the handler may read keys this walk cannot name
    return reads


def handler_body_reads(fn: Any, param_name: str) -> Optional[Set[str]]:
    """The constant keys `fn` reads from its body parameter `param_name`, or None when that cannot be told from the
    source (no source, or a use of the parameter that is not a constant-key read)."""
    node = _source_function(fn) if (inspect.isfunction(fn) or inspect.ismethod(fn)) else None
    if node is None:
        return None
    if param_name not in {a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs}:
        return None
    return _body_param_reads(node, param_name)
