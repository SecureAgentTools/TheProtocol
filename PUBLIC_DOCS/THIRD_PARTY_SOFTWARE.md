# Third-party software in a frame

A frame runs TheProtocol's own images (registry, TEG layer, event store, directory, auditor, cert-writer) beside images
that other projects publish. This page lists those images, their licences, and what each licence means for you as the
person running the frame. It is a summary, not legal advice; each project's own licence text is what applies.

## The images a frame pulls from their projects

| Image | Version in the templates | Licence | What it means for a frame |
|---|---|---|---|
| PostgreSQL | 18.6 or 16.15 (per compose file) | PostgreSQL License (permissive) | Nothing beyond keeping the notice. |
| Redis | 8.10.2 | RSALv2, SSPLv1 or AGPL-3.0 (your choice since Redis 8.0) | Use it under AGPL-3.0: running it unmodified inside a frame asks nothing of you; if you modify Redis itself and let others use it over a network, offer them your changes. |
| Redpanda | 26.2.3 | Business Source License 1.1 (not an open-source licence; each release becomes Apache-2.0 four years after it) | You may use it freely except to offer Redpanda itself as a commercial streaming or queuing service to third parties. A frame uses it privately (three fixed topics, no topic creation by anyone else, the Kafka port closed to the outside), which is ordinary use. If your organisation's policy excludes non-open-source components: the event store speaks the Kafka protocol (aiokafka), so Apache Kafka is the natural replacement, but running a frame on Apache Kafka has not been tested yet. |
| nginx | 1.30.5 | BSD-2-Clause | Nothing beyond keeping the notice. |
| PgBouncer | 1.25.2 | ISC | Nothing beyond keeping the notice. |
| SPIRE | 1.15.3 | Apache-2.0 | Nothing beyond keeping the notice. |
| Open Policy Agent, Prometheus, Alertmanager | as in the templates | Apache-2.0 | Nothing beyond keeping the notice. |
| Grafana | as in the monitoring compose | AGPL-3.0 | Running it unmodified asks nothing of you; if you modify Grafana itself and let others use it over a network, offer them your changes. |
| ntfy | as in the monitoring compose | Apache-2.0 or GPL-2.0 (your choice) | Nothing beyond keeping the notice. |

The templates name the exact versions; `docker image inspect` shows them on your host.

## What TheProtocol's own images carry

- **TheProtocol's code.** The registry, TEG layer, event store and directory are AGPL-3.0-or-later; the auditor is
  Apache-2.0. Each image names its licence, source repository and commit in its OCI labels
  (`org.opencontainers.image.licenses`, `.source`, `.revision`).
- **Python packages.** Each keeps its licence files inside the image (`site-packages/*.dist-info`). None of them is
  under a licence that conflicts with the AGPL; a few are LGPL or MPL, which is compatible.
- **The web application.** It writes the licence and notice files of every npm package it bundles to
  `THIRD_PARTY_NOTICES.txt`, served beside it. One package the frontend's dependencies list, elkjs (EPL-2.0), is
  deliberately left out of the build: its licence cannot be combined with the AGPL, and the diagram layout it provides
  is not used.
- **Base system packages.** The images are built on Debian and Alpine, whose packages keep their licences under
  `/usr/share/doc` or `/lib/apk/db`. The source of their GPL and LGPL parts is published by Debian
  (https://snapshot.debian.org) and Alpine (https://gitlab.alpinelinux.org/alpine/aports) for the exact package
  versions an image contains, and the licensor provides it on request for three years after an image was published.

## If you modify TheProtocol and run it for others

The AGPL asks you to offer the users of your modified registry its source. Set `SOURCE_CODE_URL` in the registry's
environment to the repository of your modified version: the console then shows it on every legal page. The name and
logos of TheProtocol stay with the project (LICENSING.md, Trademarks): a modified deployment wears its own name.
