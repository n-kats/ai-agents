from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("live api")
    group.addoption(
        "--run-live-api",
        action="store_true",
        default=False,
        help="Run tests that call external LLM APIs.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live_api: marks tests that require external LLM access")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-live-api"):
        return

    skip_marker = pytest.mark.skip(reason="requires --run-live-api to execute")
    for item in items:
        if "live_api" in item.keywords:
            item.add_marker(skip_marker)
