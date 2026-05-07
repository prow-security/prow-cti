# Copyright 2026 Prow Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from prow import __version__


def test_version_is_scaffold() -> None:
    assert __version__ == "0.0.0"


def test_package_imports_cleanly() -> None:
    import prow.api  # noqa: F401
    import prow.bus  # noqa: F401
    import prow.config  # noqa: F401
    import prow.connector  # noqa: F401
    import prow.db  # noqa: F401
    import prow.enrich  # noqa: F401
    import prow.stix  # noqa: F401
    import prow.taxii  # noqa: F401
    import prow.telemetry  # noqa: F401
    import prow.cli  # noqa: F401
