#!/usr/bin/env python3
"""tp — TheProtocol unified CLI entrypoint.

The umbrella binary that exposes all three personas (operator / developer /
admin) under one command. Pattern mirrors `aws`, `gh`, `kubectl`.

Legacy `tp-operator` standalone binary remains shipped alongside this for
backwards compatibility — `tp operator <verb>` and `tp-operator <verb>`
both route to the same underlying typer app.
"""
from tp_operator.umbrella import umbrella


if __name__ == "__main__":
    umbrella()
