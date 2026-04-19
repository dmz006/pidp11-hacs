"""Service-call behavior. S0: stubs + services.yaml schema check."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

EXPECTED_SERVICES = {"boot", "halt", "deposit", "examine"}


def test_services_yaml_declares_expected_services(repo_root: Path) -> None:
    data = yaml.safe_load(
        (repo_root / "custom_components" / "pidp11" / "services.yaml").read_text()
    )
    assert EXPECTED_SERVICES <= data.keys(), (
        f"services.yaml missing {EXPECTED_SERVICES - data.keys()}"
    )


@pytest.mark.xfail(reason="pending S3", strict=True)
def test_boot_service_registered() -> None:
    raise NotImplementedError("pending S3")


@pytest.mark.xfail(reason="pending S3", strict=True)
def test_halt_service_registered() -> None:
    raise NotImplementedError("pending S3")


@pytest.mark.xfail(reason="pending S3", strict=True)
def test_deposit_service_call() -> None:
    raise NotImplementedError("pending S3")


@pytest.mark.xfail(reason="pending S3", strict=True)
def test_examine_returns_value() -> None:
    raise NotImplementedError("pending S3")
