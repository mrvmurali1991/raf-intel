"""
Root-level pytest configuration for the RAF Intelligence backend test suite.

This file is loaded by pytest BEFORE pytest.ini filterwarnings are applied,
making it the correct place to install warning filters that must take effect
during module collection.

hccinfhir 0.3.x compatibility shim
-----------------------------------
hccinfhir uses the legacy importlib.resources.path() API which emits a
DeprecationWarning on Python 3.11+.  The library's load_proc_filtering()
function catches "Exception" broadly and re-raises it as RuntimeError, so
pytest's project-wide "error::DeprecationWarning" policy in pytest.ini would
otherwise block collection of any test that imports hccinfhir at module level.

Installing an "ignore" filter here — before pytest.ini is processed — lets
the library load normally.  All other DeprecationWarnings continue to be
treated as errors per the project policy.
"""
from __future__ import annotations

import warnings

# Must run before pytest.ini filterwarnings are applied.
warnings.filterwarnings(
    "ignore",
    message="path is deprecated",
    category=DeprecationWarning,
    module="importlib",
)
