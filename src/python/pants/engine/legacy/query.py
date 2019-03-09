# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from abc import abstractmethod
from builtins import object

from future.utils import text_type
from twitter.common.collections import OrderedSet

from pants.engine.addressable import BuildFileAddresses
from pants.engine.legacy.graph import OwnersRequest
from pants.engine.rules import RootRule, UnionRule, rule, union
from pants.engine.selectors import Get, Select
from pants.scm.subsystems.changed import (ChangedRequest, ChangedRequestWithScm, IncludeDependees,
                                          ScmRequest)
from pants.util.meta import AbstractClass, classproperty
from pants.util.objects import Exactly, SubclassesOf, TypedCollection, datatype
from pants.util.strutil import safe_shlex_split


class QueryParser(AbstractClass):

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


class OwnerOf(datatype([('files', TypedCollection(Exactly(text_type)))]), QueryParser):

  function_name = 'owner-of'

  @classmethod
  def parse_from_args(cls, *args):
    return cls(files=[text_type(f) for f in args])


@rule(OwnersRequest, [Select(OwnerOf)])
def owner_of_request(owner_of):
  return OwnersRequest(sources=owner_of.files, include_dependees=IncludeDependees.none)


class ChangesSince(datatype([
    ('changes_since', text_type),
    ('include_dependees', IncludeDependees),
]), QueryParser):

  function_name = 'changes-since'

  @classmethod
  def parse_from_args(cls, changes_since, include_dependees=IncludeDependees.none):
    return cls(changes_since=text_type(changes_since),
               include_dependees=IncludeDependees(include_dependees))


@rule(ChangedRequestWithScm, [Select(ChangesSince)])
def changes_since_request(changes_since):
  changed_request = ChangedRequest(
    changes_since=changes_since.changes_since,
    diffspec=None,
    include_dependees=changes_since.include_dependees,
    # TODO(#7346): parse --query expressions using the python ast module to support keyword args!
    fast=True,
  )
  return ChangedRequestWithScm(
    scm_request=ScmRequest('The changes-since query function'),
    changed_request=changed_request)


class ChangesForDiffspec(datatype([
    ('diffspec', text_type),
    ('include_dependees', IncludeDependees),
]), QueryParser):

  function_name = 'changes-for-diffspec'

  @classmethod
  def parse_from_args(cls, diffspec, include_dependees=IncludeDependees.none):
    return cls(diffspec=text_type(diffspec),
               include_dependees=IncludeDependees(include_dependees))


@rule(ChangedRequestWithScm, [Select(ChangesForDiffspec)])
def changes_for_diffspec_request(changes_for_diffspec):
  changed_request = ChangedRequest(
    changes_since=None,
    diffspec=changes_for_diffspec.diffspec,
    include_dependees=changes_for_diffspec.include_dependees,
    # TODO(#7346): parse --query expressions using the python ast module to support keyword args!
    fast=True,
  )
  return ChangedRequestWithScm(
    scm_request=ScmRequest('The changes-for-diffspec query expression'),
    changed_request=changed_request)


class Noop(object):

  function_name = 'noop'

  @classmethod
  def parse_from_args(cls):
    return cls()

  def get_noop_operator(self):
    return NoopOperator()


class Operator(AbstractClass):
  """???"""

  @abstractmethod
  def hydrate_with_input(self, build_file_addresses):
    """
    ???/produce an object containing build file addresses which has a single rule graph path to
    IntermediateResults, AND which has:
      UnionRule(QueryOperation, <type of object returned by hydrate()>)
    """


@union
class OperatorRequest(object): pass


class HydratedOperator(datatype([('operator', SubclassesOf(Operator))])): pass


class NoopOperator(Operator):

  def hydrate_with_input(self, build_file_addresses):
    return NoopOperands(build_file_addresses)


@rule(HydratedOperator, [Select(Noop)])
def hydrate_noop(noop):
  return HydratedOperator(noop.get_noop_operator())


class NoopOperands(datatype([('build_file_addresses', BuildFileAddresses)])): pass


class IntermediateResults(datatype([('build_file_addresses', BuildFileAddresses)])): pass


@rule(IntermediateResults, [Select(NoopOperands)])
def noop_results(noop_operands):
  return IntermediateResults(noop_operands.build_file_addresses)


class IntersectionOperator(datatype([('to_intersect', BuildFileAddresses)]), Operator):

  def hydrate_with_input(self, build_file_addresses):
    return IntersectionOperands(lhs=self.to_intersect,
                                rhs=build_file_addresses)


@rule(HydratedOperator, [Select(BuildFileAddresses)])
def addresses_intersection_operator(build_file_addresses):
  # TODO: this `return` is fine -- but if we had a `yield Get(...)` anywhere, it would raise a
  # `StopIteration` (a very opaque error message), inside a massive stack trace which reports every
  # single element of the `BuildFileAddresses` provided as input!
  # (1) Fix the error message for an accidental `return` somehow!
  # (2) Cut off printing the stack trace elements when they get too long! This may be done with a
  # `.print_for_stacktrace()` element on `datatype` which adds ellipses when the string gets too
  # long!
  return HydratedOperator(IntersectionOperator(build_file_addresses))


class IntersectionOperands(datatype([
    ('lhs', BuildFileAddresses),
    ('rhs', BuildFileAddresses),
])):

  def apply_intersect(self):
    lhs = OrderedSet(self.lhs.dependencies)
    rhs = OrderedSet(self.rhs.dependencies)
    return BuildFileAddresses(tuple(lhs & rhs))


@rule(IntermediateResults, [Select(IntersectionOperands)])
def intersect_results(intersection_operands):
  intersected_addresses = intersection_operands.apply_intersect()
  return IntermediateResults(intersected_addresses)


class QueryPipeline(datatype([('operator_requests', tuple)])): pass


class QueryOutput(datatype([('build_file_addresses', BuildFileAddresses)])): pass


@union
class QueryOperation(object): pass


class QueryPipelineRequest(datatype([
    ('pipeline', QueryPipeline),
    ('input_addresses', BuildFileAddresses),
])): pass


@rule(QueryOutput, [Select(QueryPipelineRequest)])
def process_query_pipeline(query_pipeline_request):
  query_pipeline = query_pipeline_request.pipeline
  build_file_addresses = query_pipeline_request.input_addresses
  for op_req in query_pipeline.operator_requests:
    hydrated_operator = yield Get(HydratedOperator, OperatorRequest, op_req)
    operator_with_input = hydrated_operator.operator.hydrate_with_input(build_file_addresses)
    results = yield Get(IntermediateResults, QueryOperation, operator_with_input)
    build_file_addresses = results.build_file_addresses
  yield QueryOutput(build_file_addresses)


class QueryParseError(Exception): pass


def parse_query_expr(known_functions, s):
  """Shlex the input string and attempt to find a query function matching the first element.

  :param dict known_functions: A dict mapping `function_name` -> `QueryParser` subclass.
  :param str s: The string argument provided to --query.
  :return: A query component which can be resolved into `BuildFileAddresses` in the v2 engine.
  :rtype: `QueryParser`
  """
  args = safe_shlex_split(s)
  name = args[0]
  rest = args[1:]
  selected_function = known_functions.get(name, None)
  if selected_function:
    return selected_function.parse_from_args(*rest)
  else:
    raise QueryParseError(
      'Query function with name {} not found (in expr {})! The known functions are: {}'
      .format(name, s, known_functions))


def query_expressions():
  """Return a list of query expressions declared in this file."""
  return [
    OwnerOf,
    ChangesSince,
    ChangesForDiffspec,
    Noop,
  ]


def rules():
  return [
    RootRule(OwnerOf),
    RootRule(ChangesSince),
    RootRule(ChangesForDiffspec),
    owner_of_request,
    changes_since_request,
    changes_for_diffspec_request,
    # We get all these for free from the previous ability to convert to a BuildFileAddresses.
    addresses_intersection_operator,
    UnionRule(OperatorRequest, OwnerOf),
    # TODO: better error message when paths can't be found through union rules!!! (just says no rule
    # could be found because we didn't make the paths yet for these union members!)
    UnionRule(OperatorRequest, ChangesSince),
    UnionRule(OperatorRequest, ChangesForDiffspec),
    UnionRule(OperatorRequest, Noop),
    hydrate_noop,
    noop_results,
    # ???/intersection
    RootRule(IntersectionOperands),
    intersect_results,
    UnionRule(QueryOperation, IntersectionOperands),
    UnionRule(QueryOperation, NoopOperands),
    # ???/query processing
    process_query_pipeline,
    RootRule(QueryPipelineRequest),
  ]
