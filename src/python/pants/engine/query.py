# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Tuple, Type, TypeVar

from pants.engine.legacy.graph import OwnersRequest
from pants.engine.rules import UnionMembership, UnionRule, RootRule, rule, union
from pants.scm.subsystems.changed import ChangedRequest, IncludeDependees
from pants.util.meta import classproperty
from pants.util.strutil import safe_shlex_split


@union
class QueryComponent(ABC):

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
class OwnerOf:
  files: Tuple[str]

  function_name = 'owner-of'

  @classmethod
  def parse_from_args(cls, *args):
    return cls(files=tuple([str(f) for f in args]))


@rule
def owner_of_request(owner_of: OwnerOf) -> OwnersRequest:
  return OwnersRequest(sources=owner_of.files, include_dependees=IncludeDependees.none)


@dataclass(frozen=True)
class ChangesSince:
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
class ChangesForDiffspec:
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



_T = TypeVar('_T', bound=QueryComponent)


@dataclass(frozen=True)
class KnownQueryExpressions:
  components: Dict[str, Type[_T]]


@rule
def known_query_expressions(union_membership: UnionMembership) -> KnownQueryExpressions:
  return KnownQueryExpressions({
    union_member.function_name: union_member
    for union_member in union_membership.union_rules[QueryComponent]
  })


@dataclass(frozen=True)
class QueryParseInput:
  expr: str


class QueryParseError(Exception): pass


# FIXME: allow returning an @union!!!
@rule
def parse_query_expr(s: QueryParseInput, known: KnownQueryExpressions) -> QueryComponent:
  """Shlex the input string and attempt to find a query function matching the first element.

  :param dict known_functions: A dict mapping `function_name` -> `QueryComponent` subclass.
  :param str s: The string argument provided to --query.
  :return: A query component which can be resolved into `BuildFileAddresses` in the v2 engine.
  :rtype: `QueryComponent`
  """
  args = safe_shlex_split(s.expr)
  name = args[0]
  rest = args[1:]
  selected_function = known.components.get(name, None)
  if selected_function:
    return selected_function.parse_from_args(*rest)
  else:
    raise QueryParseError(
      'Query function with name {} not found (in expr {})! The known functions are: {}'
      .format(name, s, known_functions))


def rules():
  return [
    RootRule(OwnerOf),
    RootRule(ChangesSince),
    RootRule(QueryParseInput),
    RootRule(ChangesForDiffspec),
    known_query_expressions,
    UnionRule(QueryComponent, OwnerOf),
    UnionRule(QueryComponent, ChangesSince),
    UnionRule(QueryComponent, ChangesForDiffspec),
    owner_of_request,
    changes_since_request,
    changes_for_diffspec_request,
    parse_query_expr,
  ]
