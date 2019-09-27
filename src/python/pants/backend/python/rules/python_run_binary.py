# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from pants.backend.python.rules.create_requirements_pex import MakePexRequest, RequirementsPex, containing_dir_if_exe
from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.build_graph.files import Files
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryWithPrefixToStrip
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.graph import BuildFileAddresses, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTargetAdaptor
from pants.engine.rules import UnionRule, optionable_rule, rule
from pants.engine.selectors import Get
from pants.option.custom_types import file_option
from pants.rules.core.run import RunResult, RunTarget
from pants.source.source_root import SourceRoot, SourceRootConfig
from pants.subsystem.subsystem import Subsystem
from pants.util.strutil import create_path_env_var


@dataclass(frozen=True)
class RunnablePex:
  filename: str
  pex: RequirementsPex
  exe_env: Dict[Any, Any]


class IncrementalPexCreation(Subsystem):
  options_scope = 'incremental-pex-creation'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--previous-incremental-pex', type=file_option, default=None, fingerprint=True,
             help='???')


@rule(RunnablePex, [PythonTargetAdaptor, PythonSetup, SourceRootConfig, SubprocessEncodingEnvironment, IncrementalPexCreation])
def create_python_binary(python_binary_target, python_setup, source_root_config, subprocess_encoding_environment, incremental_pex_creation):
  # TODO(7726): replace this with a proper API to get the `closure` for a
  # TransitiveHydratedTarget.
  transitive_hydrated_targets = yield Get(
    TransitiveHydratedTargets, BuildFileAddresses((python_binary_target.address,))
  )
  all_targets = [t.adaptor for t in transitive_hydrated_targets.closure]

  interpreter_constraints = {
    constraint
    for target_adaptor in all_targets
    for constraint in python_setup.compatibility_or_constraints(
      getattr(target_adaptor, 'compatibility', None)
    )
  }

  # Gather sources and adjust for source roots.
  # TODO: make TargetAdaptor return a 'sources' field with an empty snapshot instead of raising to
  # simplify the hasattr() checks here!
  source_roots = source_root_config.get_source_roots()
  sources_digest_to_source_roots = {}

  for maybe_source_target in all_targets:
    if not hasattr(maybe_source_target, 'sources'):
      continue
    digest = maybe_source_target.sources.snapshot.directory_digest
    spec_path = maybe_source_target.address.spec_path
    source_root = source_roots.find_by_path(spec_path)
    if maybe_source_target.type_alias == Files.alias():
      # Loose `Files`, as opposed to `Resources` or `PythonTarget`s, have no (implied) package
      # structure and so we do not remove their source root like we normally do, so that Python
      # filesystem APIs may still access the files. See pex_build_util.py's `_create_source_dumper`.
      source_root = None
    source_root_prefix = source_root.path if source_root else ""
    rel_spec_path = os.path.relpath(spec_path, source_root_prefix)
    sources_digest_to_source_roots[digest] = (
      source_root_prefix,
      rel_spec_path,
      digest.fingerprint,
    )

  stripped_sources_digests = yield [
    Get(Digest, DirectoryWithPrefixToStrip(directory_digest=digest, prefix=source_root))
    for digest, (source_root, _rel_path, _hash) in sources_digest_to_source_roots.items()
  ]

  sources_digest = yield Get(
    Digest, DirectoriesToMerge(directories=tuple(stripped_sources_digests)),
  )

  inits_digest = yield Get(InjectedInitDigest, Digest, sources_digest)

  all_input_digests = [
    sources_digest,
    inits_digest.directory_digest,
  ]
  merged_input_files = yield Get(
    Digest,
    DirectoriesToMerge,
    DirectoriesToMerge(directories=tuple(all_input_digests)),
  )

  interpreter_search_paths = create_path_env_var([
    containing_dir_if_exe(p) for p in
    python_setup.interpreter_search_paths
  ])
  pex_exe_env = {
    'PATH': interpreter_search_paths,
    **subprocess_encoding_environment.invocation_environment_dict
  }

  # Produce a pex containing pytest and all transitive 3rdparty requirements.
  output_thirdparty_requirements_pex_filename = f'{python_binary_target.address.target_name}.pex'
  all_target_requirements = {}
  for maybe_python_req_lib in all_targets:
    all_reqs_for_this_target = []
    # This is a python_requirement()-like target.
    if hasattr(maybe_python_req_lib, 'requirement'):
      single_req = str(maybe_python_req_lib.requirement)
      all_reqs_for_this_target.append(single_req)
    # This is a python_requirement_library()-like target.
    if hasattr(maybe_python_req_lib, 'requirements'):
      for py_req in maybe_python_req_lib.requirements:
        single_req = str(py_req.requirement)
        all_reqs_for_this_target.append(single_req)

    fp = hash(tuple(all_reqs_for_this_target))
    for single_req in all_reqs_for_this_target:
      all_target_requirements[single_req] = fp

  all_requirements = list(all_target_requirements.keys())
  resolved_requirements_pex = yield Get(
    RequirementsPex, MakePexRequest(
      output_filename=output_thirdparty_requirements_pex_filename,
      requirements=tuple(sorted(all_requirements)),
      interpreter_constraints=tuple(sorted(interpreter_constraints)),
      entry_point=getattr(python_binary_target, 'entry_point', None),
      input_files_digest=merged_input_files,
      source_dirs=tuple(['.']),
      previous_incremental_pex=incremental_pex_creation.get_options().previous_incremental_pex,
      fingerprinted_incremental_inputs=json.dumps({
        'sources': {
          rel_path: fp
          for _digest, (_source_root, rel_path, fp) in sources_digest_to_source_roots.items()
        },
        'requirements': all_target_requirements,
      }),
    )
  )

  yield RunnablePex(
    filename=output_thirdparty_requirements_pex_filename,
    pex=resolved_requirements_pex,
    exe_env=pex_exe_env,
  )


@rule(RunResult, [RunnablePex])
def run_python_binary(runnable_pex):
  # NB: we use the hardcoded and generic bin name `python`, rather than something dynamic like
  # `sys.executable`, to ensure that the interpreter may be discovered both locally and in remote
  # execution (so long as `env` is populated with a `PATH` env var and `python` is discoverable
  # somewhere on that PATH). This is only used to run the downloaded PEX tool; it is not
  # necessarily the interpreter that PEX will use to execute the generated .pex file.
  request = ExecuteProcessRequest(
    argv=('python', f"./{runnable_pex.filename}"),
    env=runnable_pex.exe_env,
    input_files=runnable_pex.pex.directory_digest,
    description='???'
  )

  result = yield Get(FallibleExecuteProcessResult, ExecuteProcessRequest, request)

  yield RunResult(
    status=result.exit_code,
    stdout=result.stdout.decode(),
    stderr=result.stderr.decode(),
  )


def rules():
  return [
    create_python_binary,
    run_python_binary,
    UnionRule(RunTarget, PythonTargetAdaptor),
    optionable_rule(IncrementalPexCreation),
  ]
