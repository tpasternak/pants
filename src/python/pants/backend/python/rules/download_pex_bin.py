# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.fs import Digest, Snapshot, UrlToFetch
from pants.engine.rules import rule
from pants.engine.selectors import Get
from pants.util.objects import datatype


class DownloadedPexBin(datatype([('executable', str), ('directory_digest', Digest)])):
  pass


@rule(DownloadedPexBin, [])
def download_pex_bin():
  # TODO: Inject versions and digests here through some option, rather than hard-coding it.
  # url = 'https://github.com/pantsbuild/pex/releases/download/v1.6.10/pex'
  # digest = Digest("f1d9b11e4b01c1d4088593f8f3cbd830cf98a91d5ff4ce645d076a72a7821544", 1868106)
  # snapshot = yield Get(Snapshot, UrlToFetch(url, digest))
  snapshot = yield Get(Snapshot, Digest("f1d9b11e4b01c1d4088593f8f3cbd830cf98a91d5ff4ce645d076a72a7821544", 112))
  yield DownloadedPexBin(executable=snapshot.files[0], directory_digest=snapshot.directory_digest)


def rules():
  return [
    download_pex_bin,
  ]
