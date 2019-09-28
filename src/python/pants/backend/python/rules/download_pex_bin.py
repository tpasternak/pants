# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.fs import Digest, Snapshot, UrlToFetch
from pants.engine.rules import optionable_rule, rule
from pants.engine.selectors import Get
from pants.subsystem.subsystem import Subsystem
from pants.util.objects import datatype


class PexBinSettings(Subsystem):
  options_scope = 'pex-bin-settings'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--url-fetch-digests', type=dict, fingerprint=True, default={
      'https://github.com/pantsbuild/pex/releases/download/v1.6.10/pex': Digest("f1d9b11e4b01c1d4088593f8f3cbd830cf98a91d5ff4ce645d076a72a7821544", 1868106),
    },
             help='???')
    register('--hardcoded-pex-bin-digest', type=str, fingerprint=True, default=None,
             help='???')
    register('--hardcoded-pex-bin-length', type=int, fingerprint=True, default=None,
             help='???')


class DownloadedPexBin(datatype([('executable', str), ('directory_digest', Digest)])):
  pass


@rule(DownloadedPexBin, [PexBinSettings])
def download_pex_bin(pex_bin_settings):
  maybe_hardcoded_digest = pex_bin_settings.get_options().hardcoded_pex_bin_digest
  if maybe_hardcoded_digest is not None:
    hardcoded_length = pex_bin_settings.get_options().hardcoded_pex_bin_length
    assert hardcoded_length is not None
    snapshot = yield Get(Snapshot, Digest(maybe_hardcoded_digest, hardcoded_length))
  else:
    url, digest = list(pex_bin_settings.get_options().url_fetch_digests.items())[0]
    snapshot = yield Get(Snapshot, UrlToFetch(url, digest))
  yield DownloadedPexBin(executable=snapshot.files[0], directory_digest=snapshot.directory_digest)


def rules():
  return [
    download_pex_bin,
    optionable_rule(PexBinSettings),
  ]
