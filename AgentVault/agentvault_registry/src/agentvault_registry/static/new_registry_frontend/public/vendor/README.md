# Vendored API documentation assets (§LEGALKIT, 2026-09-20)

Served by the registry at `/static/vendor/…` for the `/docs` (Swagger UI) and `/redoc` (ReDoc) pages, so that
opening the API documentation sends no request to a CDN, a font provider or the framework's website (the same
rule the console's fonts follow: Privacy Policy § 5.1 and § 8).

| file | package | version | licence |
|---|---|---|---|
| `swagger-ui-bundle.js`, `swagger-ui.css` | swagger-ui-dist | 5.9.0 | Apache-2.0 (`LICENSE.swagger-ui`; its `NOTICE.swagger-ui` is carried as Apache-2.0 § 4(d) asks) |
| `redoc.standalone.js` | redoc | 2.5.0, with one patch (below) | MIT (`LICENSE.redoc`); the notices of the libraries inside the bundle are in `redoc.standalone.js.LICENSE.txt`, the file its first line names, copied from the same package |

Upgrade by replacing the files with the same names from the package of the wanted version and updating this table.

`swagger-ui-bundle.js` is byte-identical to the file in its published package (checked 2026-09-30); `redoc.standalone.js` is identical to its package's file except for the one patch below. `swagger-ui-bundle.js` names a `swagger-ui-bundle.js.LICENSE.txt` in its first line, but swagger-ui-dist 5.9.0 does not publish that file; the package's own `LICENSE` and `NOTICE` are carried here. Replacing Swagger UI with a version whose package includes the file closes that gap.

## The one patch: ReDoc's attribution logo (2026-10-02)

ReDoc 2.5.0 renders its attribution in the menu ("API docs by Redocly") with a logo image it loads from
`https://cdn.redoc.ly/redoc/logo-mini.svg`, so every visit to `/redoc` made the visitor's browser contact Redocly's
CDN: the one request the vendoring above missed (found by the console suite's lifecycle `52-browser-storage`, run
fes-20261002T234336Z-ff1e on sandbox-a; the Cookie and Browser Storage Policy § 2 says nothing on these pages loads
from another company's servers). The patch renders no image there; the text link stays. In the bundle,

    e?n.createElement("img",{alt:"redocly logo",onError:()=>t(!1),src:"https://cdn.redoc.ly/redoc/logo-mini.svg"}):null

became `null` (one occurrence). After an upgrade, apply it again: the new bundle must load nothing from another host
(`grep -o 'cdn\.redoc\.ly' redoc.standalone.js` prints nothing), and lifecycle 52 fails on any request a page sends to
another host.
