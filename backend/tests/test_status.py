from __future__ import annotations

from app.services.status import derive_status


def test_usa_el_mayor_de_las_dos_ventanas() -> None:
    assert derive_status(45, 7) == "green"
    assert derive_status(7, 85) == "red"


def test_umbrales() -> None:
    assert derive_status(49, None) == "green"
    assert derive_status(50, None) == "yellow"
    assert derive_status(80, None) == "red"
    assert derive_status(95, None) == "critical"


def test_sin_datos_es_critical_no_green() -> None:
    assert derive_status(None, None) == "critical"
