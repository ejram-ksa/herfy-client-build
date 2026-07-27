from __future__ import annotations

from pathlib import Path

import pytest

from runtime.application.services import import_excel


def test_missing_import_file_is_rejected(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"

    with pytest.raises(ValueError, match="does not exist"):
        import_excel._read_table_rows(missing)


def test_oversized_import_file_is_rejected_before_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "oversized.csv"
    source.write_bytes(b"123456")
    monkeypatch.setattr(import_excel, "MAX_IMPORT_FILE_BYTES", 5)

    with pytest.raises(ValueError, match="too large"):
        import_excel._read_table_rows(source)


def test_csv_row_limit_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "rows.csv"
    source.write_text("code,name\n1,one\n2,two\n", encoding="utf-8")
    monkeypatch.setattr(import_excel, "MAX_IMPORT_ROWS", 2)

    with pytest.raises(ValueError, match="too many rows"):
        import_excel._read_table_rows(source)


def test_csv_column_limit_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "columns.csv"
    source.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    monkeypatch.setattr(import_excel, "MAX_IMPORT_COLUMNS", 2)

    with pytest.raises(ValueError, match="too many columns"):
        import_excel._read_table_rows(source)


def test_xlsx_row_limit_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openpyxl import Workbook

    source = tmp_path / "rows.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["code", "name"])
    worksheet.append([1, "one"])
    worksheet.append([2, "two"])
    workbook.save(source)
    workbook.close()
    monkeypatch.setattr(import_excel, "MAX_IMPORT_ROWS", 2)

    with pytest.raises(ValueError, match="too many rows"):
        import_excel._read_table_rows(source)


def test_xlsx_column_limit_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openpyxl import Workbook

    source = tmp_path / "columns.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["a", "b", "c"])
    workbook.save(source)
    workbook.close()
    monkeypatch.setattr(import_excel, "MAX_IMPORT_COLUMNS", 2)

    with pytest.raises(ValueError, match="too many columns"):
        import_excel._read_table_rows(source)


def test_valid_small_csv_remains_supported(tmp_path: Path) -> None:
    source = tmp_path / "valid.csv"
    source.write_text("material,name\n1001,Item One\n", encoding="utf-8")

    rows = import_excel._read_table_rows(source)

    assert rows == [["material", "name"], ["1001", "Item One"]]


def test_csv_total_cell_limit_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "cells.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(import_excel, "MAX_IMPORT_CELLS", 3)

    with pytest.raises(ValueError, match="too many cells"):
        import_excel._read_table_rows(source)


def test_unsupported_import_extension_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "payload.bin"
    source.write_bytes(b"material,name\n1001,Item One\n")

    with pytest.raises(ValueError, match="Unsupported import file type"):
        import_excel._read_table_rows(source)


def test_runtime_requirements_pin_defusedxml() -> None:
    requirements = (
        Path(__file__).resolve().parents[2] / "requirements.txt"
    ).read_text(encoding="utf-8").splitlines()

    assert "defusedxml==0.7.1" in requirements
