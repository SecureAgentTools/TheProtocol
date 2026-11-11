"""The TEG's own release (D6-817, V0658): the name of the image this source is built into.

The TEG's builds tag its images agentvault2-teg-layer:<release> (teg0653, teg0657, ...). This constant names that release
in the source, and the build that cuts a new image bumps it first, as the registry's build bumps BUNDLED_IMAGE_TAG
(core/registry_identity.py). It is never read from the environment: an env file can set any value, and a container would
then claim a release it is not (the registry's IMAGE_TAG once did, §V0189). Its first reader is the release comment on
every statement (database/release_sql_tag.py).
"""
TEG_RELEASE = "teg0658"
