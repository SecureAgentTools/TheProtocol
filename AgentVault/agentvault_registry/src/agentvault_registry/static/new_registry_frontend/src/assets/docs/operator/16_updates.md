# Releases, images and updates

**Checked against the source**: 2026-10-16 (the registry's `core/release_channel.py`,
`background_tasks/release_channel_checker.py` and `routers/admin_release_channel.py`; the kit's `release_channel.py`,
`frame-update.py` and `frame-up.py`; the release publisher; the operator CLI's `update`, `backup` and `restore`); the
operator CLI 1.1.8's `update` and `frame-update.py --rollback` again 2026-10-22 (the frame kit 1.0.0-beta.22)

A registry you run is updated by you, in a window you choose. What the network gives you is a **signed release
channel** that says what is out and how to get it, and a **notification** on your own registry when a stable release
or a hotfix is newer than what you run. Nothing updates itself.

## The channel

One JSON document, `https://theprotocol.cloud/downloads/frame-kit/latest.json`, signed with an Ed25519 key whose
public half ships in every reader (the registry, the operator CLI, the kit's `frame-update.py`). A reader trusts
nothing in it before the signature verifies; an unsigned or altered document reads as "no channel". The document
lists up to ten releases, newest first. Each names its version, its kind (`stable`, `hotfix` or `security`), the
registry software version it carries, the kit tarball's sha256 and URL, the digests of the six images, the oldest
version it upgrades from, a rollback note, and release notes. The registry's admin page shows the oldest version a
release upgrades from; `frame-update.py` and the CLI do not check it, so read it before you apply.

Until the public release the document is not published (the URL answers 404) and the public image namespace is
closed; a registry that checks the channel then reads "not published or unreachable" and notifies nobody.

## Images

Release images are published to `images.theprotocol.cloud/theprotocol/<name>:<version>` for the six components
(`registry`, `teg-layer`, `event-store`, `auditor`, `directory`, `cert-writer`), pullable without a login once the
channel is open, and `:stable` follows the newest release. They are built from the kit tarball the same document
names; the image labels carry the kit version and the tree digest, so an image and a tarball can be matched.
`build.sh` in the kit builds the same images from the kit's source when you prefer that.

The kit's `frame-up.py --images-prefix images.theprotocol.cloud/theprotocol --version <version>` stands a frame up
on pulled images; without the prefix it uses what `build.sh` built.

## What your registry does

With `RELEASE_CHANNEL_CHECK_ENABLED=true` the registry reads the channel every six hours
(`RELEASE_CHANNEL_CHECK_INTERVAL_SECONDS`) with a plain GET that carries no version and no identifier. Unset means
off. The kit's frame template sets it; a cloud operator's env carries it only where its provisioning wrote it, so
check `.env.operator`. When a listed release is newer than what the registry runs, it notifies its admin audience once
per version, in-app and by the pushes the admins enabled, with high priority for a hotfix or a security release, and
shows the release on the admin page **Releases** (`/#/admin/release-channel`, admin flag `admin_platform`): what runs,
what is out, the notes, the rollback note, the command to run, and a form to schedule the rollout window. The registry
reminds the admins when the window is due. It changes nothing on the host.

Opt out with `RELEASE_CHANNEL_CHECK_ENABLED=false`; point at a channel of your own with `RELEASE_CHANNEL_URL` and
`RELEASE_CHANNEL_PUBKEY_B64` (an operator who signs releases for frames of their own).

## Applying a release

On a frame stood up from the kit:

    ./frame-update.py --name <frame> --check                                 what is out, verified, against what runs
    ./frame-update.py --name <frame> --to-latest --schedule 2026-09-23T02:00:00+02:00
                                                                             a systemd timer applies it then
    ./frame-update.py --name <frame> --to-version 1.0.0-beta.12 --apply      now

The images are pulled **by the digests the signed document names**, never by a tag alone, and only the services whose
image changes are recreated, in order: the ledger first, the registry last (it migrates its database at boot). The
ledger's supply delta is read before and after, and every update is recorded in the frame's `frame-update.json`.

On a cloud operator, with the operator CLI (`tp-operator`, also `tp operator`):

    tp-operator update                                        check only (the default)
    tp-operator update --schedule 2026-09-23T02:00:00+02:00   a systemd timer runs the apply then
    tp-operator --yes update --apply --to-version <version>   now

The apply takes a snapshot first (as `tp-operator backup` does), pulls the release's images by the digests the signed
document names and tags them on the host, writes the release into `.env.operator` (`VERSION`, `IMAGES_PREFIX`, and
`IMAGE_TAG` where the file has one), recreates the stack, waits up to two minutes for every service to be healthy,
and restores the snapshot, the env included, if they are not; on success it writes the version to the stack's
`VERSION` file. A version the verified channel does not list is refused. The command the admin page prints for an
operator, `tp update --apply --to-version <version>`, is the same command under the `tp` binary.

## Rolling back

One release at a time. A release whose notes say it crossed a database migration needs the migration downgrade
before the older image starts; the release notes and the admin page say so for that release.

- **A frame.** `frame-update.py --rollback` puts back the images recorded before the last update, on any frame, a
  production one included, and prints the rolled-back release's rollback note first. Applying the previous release
  from the channel with `--to-version <previous> --apply` works too; it is pulled by digest like any other. Either
  way only images change; no database is touched. Only a local build (`--version`) stays a sandbox's.
- **A cloud operator.** The CLI's automatic rollback restores its pre-update snapshot, which holds the operator's
  registry and ledger-service databases, its env and its configuration: anything written between the snapshot and the
  restore is lost. To go back by hand, apply the previous release with `--to-version <previous>`, or restore a snapshot
  with `tp-operator restore <archive>`.

## What is disclosed

The check is an HTTPS GET of a public file from your registry's outbound address. No account, no version and no
identifier travel with it. Pulls from the public namespace need no login.
