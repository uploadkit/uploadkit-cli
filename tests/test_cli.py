"""CLI tests."""

from __future__ import annotations

import io
import json
import struct
import wave
import zipfile
from pathlib import Path

from click.testing import CliRunner
from pypdf import PdfWriter

from uploadkit_cli import main


def _pdf(path: Path) -> Path:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    path.write_bytes(buf.getvalue())
    return path


def _docx(path: Path) -> Path:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<Override PartName="/word/document.xml" '
            b'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            b"</Types>",
        )
        zf.writestr(
            "word/document.xml",
            b'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
        )
    path.write_bytes(buf.getvalue())
    return path


def _wav(path: Path) -> Path:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(struct.pack("<h", 0) * 800)
    path.write_bytes(buf.getvalue())
    return path


def test_policies_list() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["policies", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert {item["name"] for item in data} >= {"pdf", "office", "audio", "default"}


def test_doctor() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["doctor", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["uploadkit"]["ok"] is True


def test_validate_and_inspect_pdf(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "a.pdf")
    runner = CliRunner()
    result = runner.invoke(main, ["validate", str(pdf), "-e", "pdf", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["ok"] is True

    inspect = runner.invoke(main, ["inspect", str(pdf)])
    assert inspect.exit_code == 0
    payload = json.loads(inspect.output)
    assert payload["type"] == "pdf"
    assert payload["metadata"]["page_count"] == 1


def test_validate_office_and_audio(tmp_path: Path) -> None:
    runner = CliRunner()
    docx = _docx(tmp_path / "a.docx")
    wav = _wav(tmp_path / "a.wav")

    r1 = runner.invoke(main, ["validate", str(docx), "-e", "office", "--json"])
    assert r1.exit_code == 0, r1.output

    r2 = runner.invoke(main, ["validate", str(wav), "-e", "audio", "--json"])
    assert r2.exit_code == 0, r2.output


def test_simulate(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path / "sim.pdf")
    runner = CliRunner()
    result = runner.invoke(
        main, ["simulate", str(pdf), "--policy", "pdf", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["bytes"] > 0


def test_validate_rejects_bad_pdf(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not-a-pdf")
    runner = CliRunner()
    result = runner.invoke(main, ["validate", str(bad), "-e", "pdf", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["ok"] is False
