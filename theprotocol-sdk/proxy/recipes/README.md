# TheProtocol Proxy recipes

Eight of the blueprints' bridges, each a ready `proxy.yaml`, a fake of the legacy system for trying it, and a README:

| recipe | the legacy system | source | on TheProtocol | out to the legacy side |
|---|---|---|---|---|
| [meridian](meridian/) | order management | file drop (JSON) | attestation | signed evidence to the ERP folder |
| [hansa](hansa/) | terminal operating system | webhook | attestation | the ERP's API |
| [dynamo](dynamo/) | smart meters | MQTT | attestation | |
| [bazaar](bazaar/) | shop and warehouse | webhook, TheProtocol's events | attestation | fulfilment releases to the WMS, only once paid |
| [scrivener](scrivener/) | practice management | webhook | attestation | signed evidence to the DMS |
| [lyceum](lyceum/) | student records | file drop (CSV) | attestation | |
| [keystone](keystone/) | site sensor logger | SFTP | milestone evidence | |
| [trunk](trunk/) | mediation | SQL poll | payment under a mandate | the finance journal |

The other blueprints follow on the same core. The connectors and what the core guarantees: `../README.md`.
