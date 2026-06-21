"""Coordinator behavior."""

from __future__ import annotations

import inspect

import pytest


def test_parse_register_pc() -> None:
    from custom_components.pidp11.coordinator import _parse_register

    # PC response with banner re-print after the register line
    text = "EXAMINE PC\r\nPC:\t000400\r\n\r\nPDP-11 Remote Console\r\nSimulator Running...\r\n"
    assert _parse_register(text) == "000400"


def test_parse_register_psw_extra_fields() -> None:
    from custom_components.pidp11.coordinator import _parse_register

    # PSW response: octal followed by flag fields on the same line
    text = "EXAMINE PSW\r\nPSW:\t140246\tCM=U PM=K RS0 FPD0 IPL=5 TBIT0 N0 Z1 V1 C0 \r\n"
    assert _parse_register(text) == "140246"


def test_parse_register_none_on_empty() -> None:
    from custom_components.pidp11.coordinator import _parse_register

    assert _parse_register("") is None
    assert _parse_register("Simulator Running...\r\n") is None


def test_construct() -> None:
    from custom_components.pidp11.coordinator import PiDP11Coordinator, PiDP11State

    # Verify the class has the expected constructor signature.
    # Full instantiation requires a running HA event loop and frame helper;
    # we test the class shape here.
    sig = inspect.signature(PiDP11Coordinator.__init__)
    params = list(sig.parameters)
    assert "host" in params
    assert "port" in params
    assert "secret" in params

    # PiDP11State should be a dataclass with the right fields.
    state_fields = {f.name for f in PiDP11State.__dataclass_fields__.values()}
    assert {"cpu_state", "pc", "psw", "sr", "cpu_mode", "system"} == state_fields


def test_parse_cpu_mode() -> None:
    from custom_components.pidp11.coordinator import _parse_cpu_mode

    assert _parse_cpu_mode("000014") == "kernel"      # bits 15-14 = 00
    assert _parse_cpu_mode("040000") == "supervisor"  # bits 15-14 = 01
    assert _parse_cpu_mode("140000") == "user"        # bits 15-14 = 11
    assert _parse_cpu_mode(None) is None
    assert _parse_cpu_mode("invalid") is None


@pytest.mark.xfail(reason="requires HA test harness — pending S3 integration tests", strict=True)
def test_polls_show_cpu() -> None:
    raise NotImplementedError("pending S3 integration tests")


@pytest.mark.xfail(reason="requires HA test harness — pending S3 integration tests", strict=True)
def test_reconnects_on_drop() -> None:
    raise NotImplementedError("pending S3 integration tests")


@pytest.mark.xfail(reason="requires HA test harness — pending S3 integration tests", strict=True)
def test_parses_halted_state() -> None:
    raise NotImplementedError("pending S3 integration tests")
