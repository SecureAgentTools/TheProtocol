"""The built-in sources. Each is a `theprotocol.proxy.plugins.Source` found by the entry-point group
`theprotocol.proxy.sources`, and each passes `theprotocol.proxy.testing.check_source`.

V0659 (b): the file drop and the log tail, the two that need no server to test honestly. MQTT, SFTP and SQL poll are
their own orders ((k), (l), (m)), each with its container fake. V0659 (k): MQTT (its client, paho-mqtt, is the
proxy-mqtt extra and is imported only when the source starts). V0659 (l): the SFTP poll, tested against OpenSSH in a
container; its libraries come with the proxy-sftp extra and are imported only when it runs.

V0659 (m): the SQL poll (PostgreSQL, MySQL, SQL Server, SQLite). Its drivers are optional extras, imported when the
source starts, so importing this package needs none of them.
"""
from .filedrop import FileDropSource
from .logtail import LogTailSource
from .mqtt import MqttSource
from .sftp import SftpSource
from .sqlpoll import SqlPollSource

__all__ = ["FileDropSource", "LogTailSource", "MqttSource", "SftpSource", "SqlPollSource"]
