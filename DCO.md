# Developer Certificate of Origin (DCO)

TheProtocol accepts contributions under the **Developer Certificate of Origin, Version 1.1**, the
same lightweight mechanism used by the Linux kernel and thousands of other projects. There is
nothing to sign and no account to create: you certify the statement below by adding a
`Signed-off-by` line to each commit.

```bash
git commit -s -m "your change"
# adds:  Signed-off-by: Your Name <your@email>
```

The sign-off certifies, for that commit, the following (verbatim text from
developercertificate.org):

```
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.

Everybody is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.


Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```

## What this means in practice

- Contributions to the **server/platform** come in under **AGPL-3.0-or-later**; contributions to
  the **client SDKs** come in under **Apache-2.0** (inbound = outbound; see
  [`LICENSING.md`](LICENSING.md)).
- **You keep your copyright.** The sign-off is a certification of provenance, not an assignment
  and not a broad license grant beyond the component's own license.
- Use your real name and a reachable email address in the sign-off.
- Every commit in a contribution needs the sign-off; `git commit -s` (or `git rebase --signoff`
  for existing commits) does it for you.

## The DCO and the CLA

The sign-off is per commit and certifies provenance. For code, documentation and other
copyrightable material the project also asks for a one-time acceptance of the Contributor License
Agreement ([`CLA.md`](CLA.md)). It adds what a sign-off cannot carry: a patent license for the
contribution, the representation that the work is yours to give (with the employer case handled),
and the permission that lets the maintainer also license the project under commercial terms while
every contribution stays available under an open-source license. The CLA applies only to
contributions submitted after you accept it; a contribution made under the DCO alone is never
covered retroactively. [`CONTRIBUTING.md`](CONTRIBUTING.md) says how to accept it.
