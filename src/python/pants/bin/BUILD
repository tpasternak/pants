# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    '3rdparty/python/twitter/commons:twitter.common.collections',
    '3rdparty/python:setproctitle',
    'src/python/pants/backend/jvm/tasks:nailgun_task',
    'src/python/pants/base:build_environment',
    'src/python/pants/base:build_file',
    'src/python/pants/base:cmd_line_spec_parser',
    'src/python/pants/base:exceptions',
    'src/python/pants/base:exception_sink',
    'src/python/pants/base:exiter',
    'src/python/pants/base:project_tree',
    'src/python/pants/base:specs',
    'src/python/pants/base:workunit',
    'src/python/pants/binaries',
    'src/python/pants/build_graph',
    'src/python/pants/core_tasks',
    'src/python/pants/engine/legacy:address_mapper',
    'src/python/pants/engine/legacy:graph',
    'src/python/pants/engine/legacy:parser',
    'src/python/pants/engine:build_files',
    'src/python/pants/engine:fs',
    'src/python/pants/engine:legacy_engine',
    'src/python/pants/engine:mapper',
    'src/python/pants/engine:native',
    'src/python/pants/engine:parser',
    'src/python/pants/engine:scheduler',
    'src/python/pants/engine:rules',
    'src/python/pants/goal',
    'src/python/pants/goal:context',
    'src/python/pants/goal:run_tracker',
    'src/python/pants/help',
    'src/python/pants/init',
    'src/python/pants/option',
    'src/python/pants/reporting',
    'src/python/pants/pantsd:pants_daemon',
    'src/python/pants/scm/subsystems:changed',
    'src/python/pants/subsystem',
    'src/python/pants/task',
    'src/python/pants/util:contextutil',
    'src/python/pants/util:dirutil',
    'src/python/pants/util:filtering',
    'src/python/pants/util:memo',
    'src/python/pants/util:osutil',
  ],
)

# This binary's entry_point is used by the pantsbuild.pants sdist to setup a binary for
# pip installers, ie: it is why this works to get `pants` on your PATH:
# $ pip install pantsbuild.pants
# $ pants
python_binary(
  name='pants',
  entry_point='pants.bin.pants_loader:main',
  dependencies=[
    ':bin',
  ],
  # We depend on twitter.common libraries that trigger pex warnings for not properly declaring their
  # dependency on setuptools (for namespace package support).
  emit_warnings=False,
)

# This binary is for internal use only. It adds deps on internal_backends and build-support config
# files, both of which are not meant for publishing in the `pantsbuild.pants` sdist. It also adds
# deps on contrib plugins published as separate sdists from the core `pantsbuild.pants` sdist that
# this repo uses.
python_binary(
  name='pants_local_binary',
  entry_point='pants.bin.pants_loader:main',
  dependencies=[
    ':bin',
    '//:build_root',
    '//:build_tools',
    '//:pants_ini',
    '//:3rdparty_directory',
    '//:pyproject',
    'build-support/checkstyle',
    'build-support/eslint',
    'build-support/ivy',
    'build-support/mypy',
    'build-support/pylint',
    'build-support/regexes',
    'build-support/scalafmt',
    'build-support/scalastyle',
    'contrib:plugins',
    'pants-plugins/src/python/internal_backend:plugins',
  ],
  # We depend on twitter.common libraries that trigger pex warnings for not properly declaring their
  # dependency on setuptools (for namespace package support).
  emit_warnings=False,
)
