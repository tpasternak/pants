# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


python_tests(
  sources = globs('*.py', exclude=[globs('*_integration.py')]),
  dependencies = [
    '3rdparty/python/twitter/commons:twitter.common.dirutil',
    'src/python/pants/backend/codegen/antlr/python',
    'src/python/pants/base:exceptions',
    'src/python/pants/build_graph',
    'src/python/pants/testutil:test_base',
    'src/python/pants/testutil/jvm:nailgun_task_test_base',
  ]
)


python_tests(
  name = 'integration',
  sources = globs('*_integration.py'),
  dependencies = [
    'src/python/pants/testutil:int-test',
    'tests/python/pants_test:interpreter_selection_utils',
    'testprojects/src/python:antlr_directory',
    'testprojects/src/antlr/python:test_directory',
  ],
  tags = {'integration'},
)
