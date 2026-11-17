# The three starter kits the SDK ships, copied for the registry's kit check

Copied unchanged from the stack repository, `theprotocol-sdk/proxy/migrations/{csv-to-postgres,sql-to-postgres,sql-to-rest}`
at `v0664/stack-cut` 300a3bed (order gwo_9105add77686897bc940b870): tests/test_workflow_templates_shipped_kits_v0664.py
runs services/workflow_templates.check_kit over each, so a kit the SDK ships is a kit the library takes. Registry tests read
nothing outside this repo; when the SDK's kits change, copy them again and name the new commit here.
