# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from abc import ABC, abstractmethod, abstractproperty
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple, Type, TypeVar

from twitter.common.collections import OrderedSet

from pants.base.specs import SingleAddress, Specs
from pants.engine.addressable import BuildFileAddresses
from pants.engine.legacy.graph import OwnersRequest, TransitiveHydratedTargets
from pants.engine.rules import UnionMembership, UnionRule, RootRule, rule, union
from pants.engine.selectors import Get
from pants.scm.subsystems.changed import (ChangedRequest, ChangedRequestWithScm, IncludeDependees, ScmRequest)
from pants.util.meta import classproperty
from pants.util.strutil import safe_shlex_split


logger = logging.getLogger(__name__)


@union
class QueryParser(ABC):

  def quick_operator(self):
    """???"""
    return None

  @classproperty
  @abstractmethod
  def function_name(cls):
    """The initial argument of a shlexed query expression.

    If the user provides --query='<name> <args...>' on the command line, and `<name>` matches this
    property, the .parse_from_args() method is invoked with `<args...>` (shlexed, so split by
    spaces).
    """

  @classmethod
  @abstractmethod
  def parse_from_args(cls, *args):
    """Create an instance of this class from variadic positional string arguments.

    This method should raise an error if the args are incorrect or invalid.
    """

  def as_request(self):
    """???"""
    return None


@dataclass(frozen=True)
class QueryParseResult:
  parser: QueryParser


@union
class AsBuildFileAddressesRequest: pass


@union
class Operator(ABC):
  """???"""

  def quick_hydrate_with_input(self, build_file_addresses):
    """
    ???/produce an object containing build file addresses which has a single rule graph path to
    IntermediateResults, AND which has:
      UnionRule(QueryOperation, <type of object returned by hydrate()>)
    """
    return None

  def as_hydration_request(self, thts):
    """???"""
    return None


@dataclass(frozen=True)
class IntermediateResults:
  build_file_addresses: BuildFileAddresses


@union
class QueryOperation(ABC):

  @abstractmethod
  def apply(self) -> IntermediateResults: ...


@dataclass(frozen=True)
class OwnerOf(QueryParser):
  files: Tuple[str, ...]

  function_name = 'owner-of'

  @classmethod
  def parse_from_args(cls, *args):
    return cls(files=tuple([str(f) for f in args]))

  def as_request(self):
    return OwnersRequest(sources=self.files, include_dependees=IncludeDependees.none)


@dataclass(frozen=True)
class ChangesSince(QueryParser):
  changes_since: str
  include_dependees: IncludeDependees

  function_name = 'changes-since'

  @classmethod
  def parse_from_args(cls, changes_since, include_dependees=IncludeDependees.none):
    return cls(changes_since=str(changes_since),
               include_dependees=IncludeDependees(include_dependees))

  def as_request(self):
    return ChangedRequest(
      changes_since=sself.changes_since,
      diffspec=None,
      include_dependees=self.include_dependees,
      # TODO(#7346): parse --query expressions using the python ast module to support keyword args!
      fast=True,
    )


@dataclass(frozen=True)
class ChangesForDiffspec(QueryParser):
  diffspec: str
  include_dependees: IncludeDependees

  function_name = 'changes-for-diffspec'

  @classmethod
  def parse_from_args(cls, diffspec, include_dependees=IncludeDependees.none):
    return cls(diffspec=str(diffspec),
               include_dependees=IncludeDependees(include_dependees))

  def as_request(self):
    return ChangedRequest(
      changes_since=None,
      diffspec=self.diffspec,
      include_dependees=self.include_dependees,
      # TODO(#7346): parse --query expressions using the python ast module to support keyword args!
      fast=True,
    )


@dataclass(frozen=True)
class FilterOperator(Operator):
  filter_func: Callable

  def as_hydration_request(self, thts):
    return FilterOperands(
      filter_func=self.filter_func,
      thts=thts,
    )


@dataclass(frozen=True)
class FilterOperands(QueryOperation):
  filter_func: Callable
  thts: TransitiveHydratedTargets

  def apply(self) -> IntermediateResults:
    return IntermediateResults(BuildFileAddresses(tuple(
      t.address for t in self.thts.closure
      if self.filter_func(t.adaptor)
    )))



@dataclass(frozen=True)
class TypeFilter(QueryParser):
  allowed_type_aliases: Tuple[str, ...]

  function_name = 'type-filter'

  @classmethod
  def parse_from_args(cls, *allowed_type_aliases):
    return cls(allowed_type_aliases=tuple(allowed_type_aliases))

  def quick_operator(self):
    return FilterOperator(
      lambda t: t.type_alias in self.allowed_type_aliases
    )


class Noop:

  function_name = 'noop'

  @classmethod
  def parse_from_args(cls):
    return cls()

  def get_noop_operator(self):
    return NoopOperator()



@union
class OperatorRequest: pass


@dataclass(frozen=True)
class HydratedOperator:
  operator: Operator


class NoopOperator(Operator):

  def hydrate_with_input(self, build_file_addresses):
    return NoopOperands(build_file_addresses)


# @rule
# def hydrate_noop(noop: Noop) -> HydratedOperator:
#   return HydratedOperator(noop.get_noop_operator())


@dataclass(frozen=True)
class NoopOperands(QueryOperation):
  build_file_addresses: BuildFileAddresses

  def apply(self) -> IntermediateResults:
    return self.build_file_addresses


@dataclass(frozen=True)
class GetOperandsRequest:
  op: Operator
  build_file_addresses: BuildFileAddresses


@dataclass(frozen=True)
class WrappedOperands:
  operands: QueryOperation


@dataclass(frozen=True)
class IntersectionOperator(Operator):
  to_intersect: BuildFileAddresses

  def quick_hydrate_with_input(self, build_file_addresses):
    return IntersectionOperands(lhs=self.to_intersect,
                                rhs=build_file_addresses)

@rule
def hydrate_operands(req: GetOperandsRequest) -> WrappedOperands:
  maybe_quick_operands = req.op.quick_hydrate_with_input(req.build_file_addresses)
  if maybe_quick_operands is not None:
    yield WrappedOperands(maybe_quick_operands)

  thts = yield Get(TransitiveHydratedTargets, BuildFileAddresses, req.build_file_addresses)
  operands = req.op.as_hydration_request(thts)
  yield WrappedOperands(operands)


# @rule
# def addresses_intersection_operator(build_file_addresses: BuildFileAddresses) -> HydratedOperator:
#   # TODO: this `return` is fine -- but if we had a `yield Get(...)` anywhere, it would raise a
#   # `StopIteration` (a very opaque error message), inside a massive stack trace which reports every
#   # single element of the `BuildFileAddresses` provided as input!
#   # (1) Fix the error message for an accidental `return` somehow!
#   # (2) Cut off printing the stack trace elements when they get too long! This may be done with a
#   # `.print_for_stacktrace()` element on `datatype` which adds ellipses when the string gets too
#   # long!
#   return HydratedOperator(IntersectionOperator(build_file_addresses))


@dataclass(frozen=True)
class IntersectionOperands(QueryOperation):
  lhs: Optional[BuildFileAddresses]
  rhs: BuildFileAddresses

  def apply(self) -> IntermediateResults:
    if self.lhs is None:
      ret = self.rhs.dependencies
    elif self.rhs is None:
      ret = self.lhs.dependencies
    else:
      lhs = OrderedSet(self.lhs.dependencies)
      rhs = OrderedSet(self.rhs.dependencies)
      ret = lhs & rhs
    return IntermediateResults(BuildFileAddresses(tuple(ret)))


# FIXME: THIS SHOULD WORK????!!!
# @rule
# def apply_operands(operands: QueryOperation) -> IntermediateResults:
#   return operands.apply()

@rule
def apply_intersection(operands: IntersectionOperands) -> IntermediateResults:
  return operands.apply()


@dataclass(frozen=True)
class InitialSpecs:
  specs: Specs


@dataclass(frozen=True)
class InitialBuildFileAddresses:
  build_file_addresses: BuildFileAddresses


@dataclass(frozen=True)
class QueryPipeline:
  exprs: Tuple[QueryParseResult, ...]


@dataclass(frozen=True)
class QueryOutput:
  build_file_addresses: BuildFileAddresses


@dataclass(frozen=True)
class QueryPipelineRequest:
  pipeline: QueryPipeline
  input_specs: InitialSpecs


@rule
def extract_referenced_build_file_addresses(parser: QueryParseResult) -> IntermediateResults:
  req = parser.parser.as_request()
  bfa = yield Get(BuildFileAddresses, AsBuildFileAddressesRequest, req)
  yield IntermediateResults(bfa)


@rule
def hydrate_operator(parser: QueryParseResult) -> HydratedOperator:
  maybe_quick_op = parser.parser.quick_operator()
  if maybe_quick_op is not None:
    yield HydratedOperator(maybe_quick_op)

  results = yield Get(IntermediateResults, QueryParseResult, parser)
  yield HydratedOperator(IntersectionOperator(results.build_file_addresses))


@rule
def process_query_pipeline(query_pipeline_request: QueryPipelineRequest) -> QueryOutput:
  query_pipeline = query_pipeline_request.pipeline
  init_specs = query_pipeline_request.input_specs
  build_file_addresses = None
  if init_specs.specs is not None:
    initial_build_file_addresses = yield Get(InitialBuildFileAddresses, InitialSpecs, init_specs)
    build_file_addresses = initial_build_file_addresses.build_file_addresses
    logger.debug(f'initial addresses: {build_file_addresses.addresses}')
  for expr in query_pipeline.exprs:
    logger.debug(f'expr: {expr}')
    dehydrated_operator = yield Get(HydratedOperator, QueryParseResult, expr)
    operands = yield Get(WrappedOperands, GetOperandsRequest(
      op=dehydrated_operator.operator,
      build_file_addresses=build_file_addresses,
    ))
    logger.debug(f'operands: {operands}')
    results = operands.operands.apply()
    build_file_addresses = results.build_file_addresses
  yield QueryOutput(build_file_addresses)


_T = TypeVar('_T', bound=QueryParser)


@dataclass(frozen=True)
class KnownQueryExpressions:
  components: Dict[str, Type[_T]]


@rule
def known_query_expressions(union_membership: UnionMembership) -> KnownQueryExpressions:
  return KnownQueryExpressions({
    union_member.function_name: union_member
    for union_member in union_membership.union_rules[QueryParser]
  })


@dataclass(frozen=True)
class QueryParseInput:
  expr: str


class QueryParseError(Exception): pass


# FIXME: allow returning an @union!!!
@rule
def parse_query_expr(s: QueryParseInput, known: KnownQueryExpressions) -> QueryParseResult:
  """Shlex the input string and attempt to find a query function matching the first element.

  :param dict known_functions: A dict mapping `function_name` -> `QueryParser` subclass.
  :param str s: The string argument provided to --query.
  :return: A query component which can be resolved into `BuildFileAddresses` in the v2 engine.
  :rtype: `QueryParser`
  """
  args = safe_shlex_split(s.expr)
  name = args[0]
  rest = args[1:]
  selected_function = known.components.get(name, None)
  if selected_function:
    return QueryParseResult(selected_function.parse_from_args(*rest))
  else:
    raise QueryParseError(
      'Query function with name {} not found (in expr {})! The known functions are: {}'
      .format(name, s, known_functions))


def rules():
  return [
    RootRule(ChangesForDiffspec),
    RootRule(ChangesSince),
    RootRule(IntersectionOperands),
    RootRule(OwnerOf),
    RootRule(QueryParseInput),
    RootRule(QueryPipelineRequest),
    UnionRule(OperatorRequest, ChangesForDiffspec),
    UnionRule(OperatorRequest, ChangesSince),
    UnionRule(OperatorRequest, OwnerOf),
    # UnionRule(OperatorRequest, Noop),
    # FIXME: these aren't useful yet!!!
    # UnionRule(Operator, Noop),
    # UnionRule(Operator, IntersectionOperands),
    UnionRule(QueryParser, ChangesForDiffspec),
    UnionRule(QueryParser, ChangesSince),
    UnionRule(QueryParser, OwnerOf),
    UnionRule(QueryParser, TypeFilter),
    UnionRule(QueryOperation, IntersectionOperands),
    # UnionRule(QueryOperation, NoopOperands),
    # addresses_intersection_operator,
    known_query_expressions,
    apply_intersection,
    parse_query_expr,
    process_query_pipeline,
    UnionRule(AsBuildFileAddressesRequest, OwnersRequest),
    UnionRule(AsBuildFileAddressesRequest, ChangedRequest),
    extract_referenced_build_file_addresses,
    hydrate_operator,
    UnionRule(Operator, FilterOperator),
    UnionRule(QueryOperation, FilterOperands),
    hydrate_operands,
  ]
