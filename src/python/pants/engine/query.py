# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Tuple, Type, TypeVar

from twitter.common.collections import OrderedSet

from pants.base.specs import SingleAddress, Specs
from pants.engine.addressable import BuildFileAddresses
from pants.engine.legacy.graph import OwnersRequest
from pants.engine.rules import UnionMembership, UnionRule, RootRule, rule, union
from pants.engine.selectors import Get
from pants.scm.subsystems.changed import (ChangedRequest, ChangedRequestWithScm, IncludeDependees, ScmRequest)
from pants.util.meta import classproperty
from pants.util.strutil import safe_shlex_split


@union
class QueryParser(ABC):

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


@dataclass(frozen=True)
class OwnerOf(QueryParser):
  files: Tuple[str]

  function_name = 'owner-of'

  @classmethod
  def parse_from_args(cls, *args):
    return cls(files=tuple([str(f) for f in args]))


@rule
def owner_of_request(owner_of: OwnerOf) -> OwnersRequest:
  return OwnersRequest(sources=owner_of.files, include_dependees=IncludeDependees.none)


@dataclass(frozen=True)
class ChangesSince(QueryParser):
  changes_since: str
  include_dependees: IncludeDependees

  function_name = 'changes-since'

  @classmethod
  def parse_from_args(cls, changes_since, include_dependees=IncludeDependees.none):
    return cls(changes_since=str(changes_since),
               include_dependees=IncludeDependees(include_dependees))


@rule
def changes_since_request(changes_since: ChangesSince) -> ChangedRequest:
  return ChangedRequest(
    changes_since=changes_since.changes_since,
    diffspec=None,
    include_dependees=changes_since.include_dependees,
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


@rule
def changes_for_diffspec_request(changes_for_diffspec: ChangesForDiffspec) -> ChangedRequest:
  return ChangedRequest(
    changes_since=None,
    diffspec=changes_for_diffspec.diffspec,
    include_dependees=changes_for_diffspec.include_dependees,
    # TODO(#7346): parse --query expressions using the python ast module to support keyword args!
    fast=True,
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


@union
class Operator(ABC):
  """???"""

  @abstractmethod
  def hydrate_with_input(self, build_file_addresses):
    """
    ???/produce an object containing build file addresses which has a single rule graph path to
    IntermediateResults, AND which has:
      UnionRule(QueryOperation, <type of object returned by hydrate()>)
    """


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
class IntermediateResults:
  build_file_addresses: BuildFileAddresses


@union
class QueryOperation(ABC):

  @abstractmethod
  def apply(self) -> IntermediateResults: ...


@dataclass(frozen=True)
class NoopOperands(QueryOperation):
  build_file_addresses: BuildFileAddresses

  def apply(self) -> IntermediateResults:
    return self.build_file_addresses


@dataclass(frozen=True)
class IntersectionOperator(Operator):
  to_intersect: BuildFileAddresses

  def hydrate_with_input(self, build_file_addresses):
    return IntersectionOperands(lhs=self.to_intersect,
                                rhs=build_file_addresses)


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
  lhs: BuildFileAddresses
  rhs: BuildFileAddresses

  def apply(self) -> IntermediateResults:
    lhs = OrderedSet(self.lhs.dependencies)
    rhs = OrderedSet(self.rhs.dependencies)
    return IntermediateResults(BuildFileAddresses(tuple(lhs & rhs)))


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
  exprs: Tuple[QueryParser, ...]


@dataclass(frozen=True)
class QueryOutput:
  build_file_addresses: BuildFileAddresses


@dataclass(frozen=True)
class QueryPipelineRequest:
  pipeline: QueryPipeline
  input_specs: InitialSpecs


@rule
def process_query_pipeline(query_pipeline_request: QueryPipelineRequest) -> QueryOutput:
  query_pipeline = query_pipeline_request.pipeline
  initial_build_file_addresses = yield Get(InitialBuildFileAddresses, InitialSpecs, query_pipeline_request.input_specs)
  build_file_addresses = initial_build_file_addresses.build_file_addresses
  for expr in query_pipeline.exprs:
    raise Exception(f'wow!!! {expr}')
    # cur_owners_request = yield Get(OwnersRequest, OwnerOf, expr)
    # cur_addresses = yield Get(BuildFileAddresses, OwnersRequest, cur_owners_request)
    # hydrated_operator = yield Get(HydratedOperator, BuildFileAddresses, cur_addresses)
    # hydrated_operator = yield Get(HydratedOperator, QueryParser, component)
    raise Exception(f'wow!!! {cur_owners_request}')
    operator_with_input = hydrated_operator.operator.hydrate_with_input(build_file_addresses)
    # FIXME: THIS SHOULD WORK????!!!
    # results = yield Get(IntermediateResults, QueryOperation, operator_with_input)
    # results = yield Get(IntermediateResults, IntersectionOperands, operator_with_input)
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


@dataclass(frozen=True)
class QueryParseResult:
  parser: QueryParser


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
    UnionRule(QueryOperation, IntersectionOperands),
    # UnionRule(QueryOperation, NoopOperands),
    # addresses_intersection_operator,
    changes_for_diffspec_request,
    changes_since_request,
    # hydrate_noop,
    known_query_expressions,
    apply_intersection,
    owner_of_request,
    parse_query_expr,
    process_query_pipeline,
  ]
