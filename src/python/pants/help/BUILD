# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
  dependencies=[
    'src/python/pants/base:build_environment',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/goal',
    'src/python/pants/option',
    'src/python/pants/subsystem',
    'src/python/pants/util:memo',
  ],
  tags = {"partially_type_checked"},
)

python_tests(
  name='integration',
  dependencies=[
    'src/python/pants/testutil:int-test',
  ],
  tags = {'integration'},
)
