# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum
from dataclasses import dataclass
from typing import Any, Tuple

from pants.engine.rules import RootRule, rule
from pants.goal.workspace import ScmWorkspace
from pants.scm.scm import Scm
from pants.subsystem.subsystem import Subsystem


class IncludeDependees(Enum):
  none = 'none'
  direct = 'direct'
  transitive = 'transitive'


@dataclass(frozen=True)
class ChangedRequest:
  """Parameters required to compute a changed file/target set."""
  changes_since: Any
  diffspec: Any
  include_dependees: IncludeDependees
  fast: bool

  @classmethod
  def from_options(cls, options):
    """Given an `Options` object, produce a `ChangedRequest`."""
    return cls(options.changes_since,
               options.diffspec,
               options.include_dependees,
               options.fast or False)

  def is_actionable(self):
    return bool(self.changes_since or self.diffspec)


class Changed(Subsystem):
  """A subsystem for global `changed` functionality.

  This supports the "legacy" `changed`, `test-changed` and `compile-changed` goals as well as the
  v2 engine style `--changed-*` argument target root replacements which can apply to any goal (e.g.
  `./pants --changed-parent=HEAD~3 list` replaces `./pants --changed-parent=HEAD~3 changed`).
  """
  options_scope = 'changed'

  @classmethod
  def register_options(cls, register):
    register('--changes-since', '--parent', '--since',
             help='Calculate changes since this tree-ish/scm ref (defaults to current HEAD/tip).')
    register('--diffspec',
             help='Calculate changes contained within given scm spec (commit range/sha/ref/etc).')
    register('--include-dependees', type=IncludeDependees, default=IncludeDependees.none,
             help='Include direct or transitive dependees of changed targets.')
    register('--fast', type=bool,
             help='Stop searching for owners once a source is mapped to at least one owning target.')



@dataclass(frozen=True)
class ChangedFilesResult:
  changed_files: Tuple[str]


@dataclass(frozen=True)
class ScmResult:
  scm: Scm


@dataclass(frozen=True)
class ScmRequest:
  reason_for_scm: str


class ScmRequestFailed(Exception): pass


@rule
def try_get_scm(scm_request: ScmRequest) -> ScmResult:
  # TODO: if this is a blocking call, convert it to v2 rules as well!
  scm = get_scm()
  if not scm:
    raise ScmRequestFailed(
      # TODO: centralize the error messaging for when an SCM is required, and describe what SCMs
      # are supported!
      '{} are not available without a recognized SCM (usually git).'
      .format(scm_request.reason_for_scm)
    )
  return ScmResult(scm)


@dataclass(frozen=True)
class ChangedRequestWithScm:
  scm_request: ScmRequest
  changed_request: ChangedRequest


@dataclass(frozen=True)
class ChangedFilesResult:
  changed_files: Tuple[str, ...]


# TODO: ensure this rule isn't ever cached with an @ensure_daemon integration test!
@rule
def get_changed(changed_request_with_scm: ChangedRequestWithScm) -> ChangedFilesResult:
  scm_result = yield Get(ScmResult, ScmRequest, changed_request_with_scm.scm_request)
  scm = scm_result.scm
  changed_request = changed_request_with_scm.changed_request
  workspace = ScmWorkspace(scm)
  diffspec = changed_request.diffspec
  if diffspec:
    # TODO: this does a synchronous process invocation to git under the hood -- rewrite!
    result = workspace.changes_in(diffspec)
  else:
    # .current_rev_identifier() is just a static string for git right now (not slow to access).
    changes_since = changed_request.changes_since or scm.current_rev_identifier()
    result = workspace.touched_files(changes_since)
  yield ChangedFilesResult(changed_files=result)


def rules():
  return [
    try_get_scm,
    RootRule(ChangedRequestWithScm),
    get_changed,
  ]
