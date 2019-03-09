# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot, get_scm
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.specs import SingleAddress, Specs
from pants.base.target_roots import TargetRoots
from pants.engine.addressable import BuildFileAddresses
from pants.engine.legacy.graph import OwnersRequest
from pants.engine.query import QueryComponent, QueryParseInput
from pants.engine.selectors import Params
from pants.scm.subsystems.changed import ChangedRequest, IncludeDependees, ScmWrapper


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
    :returns: A `Specs` object.
    """
    build_root = build_root or get_buildroot()
    spec_parser = CmdLineSpecParser(build_root)

    dependencies = tuple(OrderedSet(spec_parser.parse_spec(spec_str) for spec_str in target_specs))
    return Specs(
      dependencies=dependencies,
      exclude_patterns=exclude_patterns if exclude_patterns else tuple(),
      tags=tags)

  @classmethod
  def create(cls, options, session, build_root=None, exclude_patterns=None, tags=None):
    """
    :param Options options: An `Options` instance to use.
    :param session: The Scheduler session
    :param string build_root: The build root.
    """
    # Determine the literal target roots.
    spec_roots = cls.parse_specs(
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

    # Parse --query expressions into objects which can be resolved into BuildFileAddresses via v2
    # rules.
    query_expr_strings = options.for_global_scope().query
    exprs = session.product_request(
      QueryComponent,
      [QueryParseInput(s) for s in query_expr_strings])

    logger.debug('spec_roots are: %s (%s)', spec_roots, bool(spec_roots))
    logger.debug('changed_request is: %s (%s)', changed_request, bool(changed_request.is_actionable()))
    logger.debug('owned_files are: %s (%s)', owned_files, bool(owned_files))
    logger.debug('query exprs are: %s (%s)', exprs, bool(exprs))
    targets_specified = sum(
      1 for item
      in (changed_request.is_actionable(), owned_files, spec_roots, exprs)
      if item)

    if targets_specified > 1:
      # We've been provided more than one of: a change request, an owner request, a query request,
      # or spec roots.
      raise InvalidSpecConstraint(
        'Multiple target selection methods provided. Please use only one of '
        '--changed-*, --owner-of, --query, or target specs'
      )

    def scm(entity):
      scm = get_scm()
      if not scm:
        raise InvalidSpecConstraint(
          # TODO: centralize the error messaging for when an SCM is required, and describe what SCMs
          # are supported!
          '{} are not available without a recognized SCM (usually git).'
          .format(entity)
        )
      return scm

    if changed_request.is_actionable():
      # We've been provided no spec roots (e.g. `./pants list`) AND a changed request. Compute
      # alternate target roots.
      scm = scm('The --changed-* options')
      changed_addresses, = session.product_request(
        BuildFileAddresses,
        [Params(ScmWrapper(scm), changed_request)])
      logger.debug('changed addresses: %s', changed_addresses)
      dependencies = tuple(SingleAddress(a.spec_path, a.target_name) for a in changed_addresses)
      return TargetRoots(Specs(dependencies=dependencies, exclude_patterns=exclude_patterns, tags=tags))
    elif owned_files:
      # We've been provided no spec roots (e.g. `./pants list`) AND a owner request. Compute
      # alternate target roots.
      request = OwnersRequest(sources=tuple(owned_files), include_dependees=IncludeDependees.none)
      owner_addresses, = session.product_request(BuildFileAddresses, [request])
      logger.debug('owner addresses: %s', owner_addresses)
      dependencies = tuple(SingleAddress(a.spec_path, a.target_name) for a in owner_addresses)
      return TargetRoots(Specs(dependencies=dependencies, exclude_patterns=exclude_patterns, tags=tags))
    elif exprs:
      # TODO: this should only be necessary for the `changed-since`/etc queries! This can be done by
      # returning a dummy ScmWrapper if no `changed-*` queries are used!
      scm = scm('The --query option')
      # TODO(#7346): deprecate --owner-of and --changed-* in favor of --query versions, allow
      # pipelining of successive query expressions with the command-line target specs as the initial
      # input!
      if len(exprs) > 1:
        raise ValueError('Only one --query argument is currently supported! Received: {}.'
                         .format(exprs))
      expr_addresses, = session.product_request(
        BuildFileAddresses,
        [Params(ScmWrapper(scm), exprs[0])])
      logger.debug('expr addresses: %s', expr_addresses)
      dependencies = tuple(SingleAddress(a.spec_path, a.target_name) for a in expr_addresses)
      return TargetRoots(Specs(dependencies=dependencies, exclude_patterns=exclude_patterns, tags=tags))
    else:
      return TargetRoots(spec_roots)
