# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from typing import Tuple

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.specs import SingleAddress, Specs
from pants.base.target_roots import TargetRoots
from pants.engine.addressable import BuildFileAddresses
from pants.engine.legacy.graph import OwnersRequest
from pants.engine.query import (InitialBuildFileAddresses, InitialSpecs, QueryParser, QueryParseResult, QueryParseInput, QueryOutput, QueryPipeline, QueryPipelineRequest)
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, Params
from pants.option.options import Options
from pants.scm.subsystems.changed import (ChangedRequest, ChangedRequestWithScm, IncludeDependees,
                                          ScmRequest, ScmRequestFailed)


logger = logging.getLogger(__name__)


class InvalidSpecConstraint(Exception):
  """Raised when invalid constraints are given via target specs and arguments like --changed*."""


class TargetRootsCalculator:
  """Determines the target roots for a given pants run."""

  @classmethod
  def parse_specs(cls, target_specs, build_root=None, exclude_patterns=None, tags=None):
    """Parse string specs into unique `Spec` objects.

    :param iterable target_specs: An iterable of string specs.
    :param string build_root: The path to the build root.
    :returns: A `Specs`, or None.
    """
    build_root = build_root or get_buildroot()
    spec_parser = CmdLineSpecParser(build_root)

    dependencies = tuple(OrderedSet(spec_parser.parse_spec(spec_str) for spec_str in target_specs))
    if not dependencies:
      return None
    return Specs(
      dependencies=dependencies,
      exclude_patterns=exclude_patterns if exclude_patterns else tuple(),
      tags=tags,
    )

  @classmethod
  def _make_specs(cls, build_file_addresses, exclude_patterns=None, tags=None):
    return Specs(
      dependencies=tuple(SingleAddress(a.spec_path, a.target_name) for a in build_file_addresses),
      exclude_patterns=exclude_patterns,
      tags=tags,
    )

  @classmethod
  def create(cls, options, session, build_root=None, exclude_patterns=None, tags=None):
    """
    :param Options options: An `Options` instance to use.
    :param session: The Scheduler session
    :param string build_root: The build root.
    """

    try:
      target_roots, = session.product_request(TargetRoots, [Params(
        TargetRootsRequest(
          options=options,
          build_root=build_root,
          exclude_patterns=exclude_patterns,
          tags=tags,
        ),
        ScmRequest('The --query option'),
      )])
    except ScmRequestFailed as e:
      raise InvalidSpecConstraint(str(e))

    logger.debug(f'target_roots: {target_roots}')
    return target_roots


@dataclass(frozen=True)
class TargetRootsRequest:
  options: Options
  build_root: str
  exclude_patterns: Tuple[str, ...]
  tags: Tuple[str, ...]


@rule
def get_initial_bfa(init_specs: InitialSpecs) -> InitialBuildFileAddresses:
  bfa = yield Get(BuildFileAddresses, Specs, (init_specs.specs or Specs([])))
  yield InitialBuildFileAddresses(bfa)


@rule
def resolve_starting_specs(target_roots_request: TargetRootsRequest) -> InitialSpecs:
  """Determine the "starting" addresses, which become the initial input to a --query pipeline.

  If no --query arguments are provided, the result of this method becomes the target roots. Only one
  of --owner-of, --changed-*, or target specs may be provided. While --query also supports
  e.g. `owner-of <file>` and `changes-since <ref>` expressions, --owner-of and --changed-* are still
  supported on the command line in order to make it explicit what the initial target input is, since
  that has a significant effect on the result of the pipeline and likely on the total pants runtime.
  TODO: --query *could* allow removing --owner-of and --changed-* entirely, by just ensuring that
  the first element of the query pipeline is an expression convertible to a specific set of
  BuildFileAddresses (e.g. `owner-of <file>`), instead of a filter (e.g. `filter
  type=junit_tests`). This special-case logic feels confusing, and it seems clearer to separate the
  method of getting the initial input to the query pipeline. This could easily change.
  """
  options = target_roots_request.options
  build_root = target_roots_request.build_root
  exclude_patterns = target_roots_request.exclude_patterns
  tags = target_roots_request.tags

  # Determine the target specs from the command line, if any.
  literal_specs = TargetRootsCalculator.parse_specs(
    target_specs=options.target_specs,
    build_root=build_root,
    exclude_patterns=exclude_patterns,
    tags=tags)

  # Determine `Changed` arguments directly from options to support pre-`Subsystem`
  # initialization paths.
  changed_options = options.for_scope('changed')
  changed_request = ChangedRequest.from_options(changed_options)

  # Determine the `--owner-of=` arguments provided from the global options
  owned_files = options.for_global_scope().owner_of

  logger.debug('literal_specs are: %s', literal_specs)
  logger.debug('changed_request is: %s', changed_request)
  logger.debug('owned_files are: %s', owned_files)
  targets_specified = sum(1 for item
                       in (changed_request.is_actionable(), owned_files, literal_specs)
                       if item)

  if targets_specified > 1:
    # We've been provided more than one of: a change request, an owner request, a query request,
    # or spec roots.
    raise InvalidSpecConstraint(
      'Multiple target selection methods provided. Please use only one of '
      '--changed-*, --owner-of, or target specs.'
    )

  if changed_request.is_actionable():
    # We've been provided no spec roots (e.g. `./pants list`) AND a changed request. Compute
    # alternate target roots.
    changed_addresses = yield Get(BuildFileAddresses, ChangedRequestWithScm(
      scm_request=ScmRequest('The --changed-* options'),
      changed_request=changed_request,
    ))
    logger.debug('changed addresses: %s', changed_addresses)
    specs = TargetRootsCalculator._make_specs(
      changed_addresses, exclude_patterns=exclude_patterns, tags=tags)
  elif owned_files:
    # We've been provided no spec roots (e.g. `./pants list`) AND a owner request. Compute
    # alternate target roots.
    owner_addresses = yield Get(BuildFileAddresses, OwnersRequest(
      sources=tuple(owned_files),
      include_dependees=IncludeDependees.none,
    ))
    logger.debug('owner addresses: %s', owner_addresses)
    specs = TargetRootsCalculator._make_specs(
      owner_addresses, exclude_patterns=exclude_patterns, tags=tags)
  else:
    specs = literal_specs

  # TODO: this somehow deadlocks if you yield Specs instead of InitialSpecs -- FIX THIS!!!
  yield InitialSpecs(specs)


@rule
def get_target_roots(target_roots_request: TargetRootsRequest) -> TargetRoots:
  initial_specs = yield Get(InitialSpecs, TargetRootsRequest, target_roots_request)

  options = target_roots_request.options
  exclude_patterns = target_roots_request.exclude_patterns
  tags = target_roots_request.tags

  # Parse --query expressions into objects which can be resolved into BuildFileAddresses via v2
  # rules.
  query_expr_strings = options.for_global_scope().query
  exprs = yield [Get(QueryParseResult, QueryParseInput(s)) for s in query_expr_strings]
  logger.debug('query exprs are: %s', exprs)

  if not exprs:
    yield TargetRoots(initial_specs.specs)

  # TODO(#7346): deprecate --owner-of and --changed-* in favor of --query versions, allow
  # pipelining of successive query expressions with the command-line target specs as the initial
  # input!
  # if len(exprs) > 1:
  #   raise ValueError('Only one --query argument is currently supported! Received: {}.'
  #                    .format(exprs))
  query_pipeline = QueryPipeline(tuple(exprs))
  query_output = yield Get(QueryOutput, QueryPipelineRequest(
    pipeline=query_pipeline,
    input_specs=initial_specs,
  ))
  expr_addresses = query_output.build_file_addresses
  logger.debug('expr addresses: %s', expr_addresses.addresses)
  final_specs = TargetRootsCalculator._make_specs(
    expr_addresses, exclude_patterns=exclude_patterns, tags=tags)

  yield TargetRoots(final_specs)


def rules():
  return [
    RootRule(TargetRootsRequest),
    resolve_starting_specs,
    get_target_roots,
    get_initial_bfa,
  ]
