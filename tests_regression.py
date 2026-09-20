import unittest

import gui_pipeline_regression_tests
import hook_concatenation_regression_tests
import pipeline_regression_tests


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromModule(pipeline_regression_tests))
    suite.addTests(loader.loadTestsFromModule(hook_concatenation_regression_tests))
    suite.addTests(loader.loadTestsFromModule(gui_pipeline_regression_tests))
    return suite
