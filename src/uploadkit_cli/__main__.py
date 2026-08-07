"""UploadKit developer CLI."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import click
from uploadkit import Uploader, UploaderError, UploadPolicy
from uploadkit_testing import FakeStorageProvider, make_upload_file

try:
    from uploadkit_security import default_validators
except ImportError:  # pragma: no cover
    default_validators = None  # type: ignore[assignment]


def _serialize(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        data = asdict(obj)
        for key, value in list(data.items()):
            if hasattr(value, "value"):
                data[key] = value.value
        return data
    if hasattr(obj, "value"):
        return obj.value
    return obj


def _read_path(path: Path) -> bytes:
    return path.read_bytes()


def _build_policy(
    extras: tuple[str, ...],
    *,
    max_size: int | None,
) -> UploadPolicy:
    validators: list[Any] = []
    async_validators: list[Any] = []
    extensions: set[str] = set()
    mimes: set[str] = set()

    if default_validators is not None:
        # Feature packages own content-type checks; keep generic security
        # validators but drop MIME when extras are active to avoid ZIP/OOXML
        # mismatches from signature sniffing.
        if extras:
            from uploadkit_security import MimeTypeValidator

            validators.extend(default_validators(exclude=MimeTypeValidator))
        else:
            validators.extend(default_validators())

    for extra in extras:
        name = extra.lower()
        if name == "pdf":
            from uploadkit_pdf import PdfPolicy

            p = PdfPolicy(max_size=max_size)
            validators.extend(p.validators)
            async_validators.extend(p.async_validators)
            extensions |= set(p.allowed_extensions)
            mimes |= set(p.allowed_mime_types)
        elif name == "office":
            from uploadkit_office import OfficePolicy

            p = OfficePolicy(max_size=max_size)
            validators.extend(p.validators)
            async_validators.extend(p.async_validators)
            extensions |= set(p.allowed_extensions)
            mimes |= set(p.allowed_mime_types)
        elif name == "audio":
            from uploadkit_audio import AudioPolicy

            p = AudioPolicy(max_size=max_size)
            validators.extend(p.validators)
            async_validators.extend(p.async_validators)
            extensions |= set(p.allowed_extensions)
            mimes |= set(p.allowed_mime_types)
        else:
            raise click.ClickException(f"Unknown extra: {extra}")

    return UploadPolicy(
        max_size=max_size,
        allowed_extensions=frozenset(extensions),
        allowed_mime_types=frozenset(mimes),
        validators=tuple(validators),
        async_validators=tuple(async_validators),
    )


def _detect_inspect(path: Path) -> dict[str, Any]:
    data = _read_path(path)
    suffix = path.suffix.lower().lstrip(".")
    result: dict[str, Any] = {"path": str(path), "size": len(data), "extension": suffix}

    if suffix == "pdf" or data.lstrip().startswith(b"%PDF"):
        try:
            from uploadkit_pdf import inspect_pdf

            result["type"] = "pdf"
            result["metadata"] = _serialize(inspect_pdf(data))
            return result
        except ImportError:
            result["type"] = "pdf"
            result["error"] = "uploadkit-pdf not installed"
            return result
        except Exception as exc:  # noqa: BLE001
            result["type"] = "pdf"
            result["error"] = str(exc)
            return result

    if suffix in {"docx", "xlsx", "pptx", "odt", "ods"} or data.startswith(b"PK\x03\x04"):
        try:
            from uploadkit_office import inspect_office

            result["type"] = "office"
            result["metadata"] = _serialize(inspect_office(data, filename=path.name))
            return result
        except ImportError:
            result["type"] = "office"
            result["error"] = "uploadkit-office not installed"
            return result
        except Exception as exc:  # noqa: BLE001
            # Might be a non-office ZIP; fall through to audio/generic
            if suffix in {"docx", "xlsx", "pptx", "odt", "ods"}:
                result["type"] = "office"
                result["error"] = str(exc)
                return result

    if suffix in {"mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "webm"}:
        try:
            from uploadkit_audio import inspect_audio

            result["type"] = "audio"
            result["metadata"] = _serialize(inspect_audio(data, filename=path.name))
            return result
        except ImportError:
            result["type"] = "audio"
            result["error"] = "uploadkit-audio not installed"
            return result
        except Exception as exc:  # noqa: BLE001
            result["type"] = "audio"
            result["error"] = str(exc)
            return result

    result["type"] = "unknown"
    return result


@click.group()
@click.version_option(package_name="uploadkit-cli")
def main() -> None:
    """UploadKit developer tooling."""


@main.command("validate")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-e",
    "--extra",
    "extras",
    multiple=True,
    type=click.Choice(["pdf", "office", "audio"], case_sensitive=False),
    help="Enable feature-package validators.",
)
@click.option("--max-size", type=int, default=50 * 1024 * 1024, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON for CI.")
def validate_cmd(
    path: Path,
    extras: tuple[str, ...],
    max_size: int,
    as_json: bool,
) -> None:
    """Validate PATH against Core/security and optional feature packages."""
    if not extras:
        # Infer from extension when possible
        suffix = path.suffix.lower().lstrip(".")
        if suffix == "pdf":
            extras = ("pdf",)
        elif suffix in {"docx", "xlsx", "pptx", "odt", "ods"}:
            extras = ("office",)
        elif suffix in {"mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "webm"}:
            extras = ("audio",)

    try:
        policy = _build_policy(extras, max_size=max_size)
    except ImportError as exc:
        raise click.ClickException(
            f"Missing optional dependency: {exc}. "
            "Install extras e.g. pip install 'uploadkit-cli[pdf]'"
        ) from exc

    storage = FakeStorageProvider()
    uploader = Uploader(policy, storage)
    data = _read_path(path)
    try:
        uploader.upload(
            make_upload_file(data, name=path.name),
            bucket="validate",
            object_name=path.name,
        )
    except UploaderError as exc:
        payload = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
        if as_json:
            click.echo(json.dumps(payload))
        else:
            click.echo(f"FAIL: {exc}", err=True)
        sys.exit(1)

    payload = {"ok": True, "path": str(path), "extras": list(extras)}
    if as_json:
        click.echo(json.dumps(payload))
    else:
        click.echo(f"OK: {path}")


@main.command("inspect")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def inspect_cmd(path: Path) -> None:
    """Dump type-specific metadata as JSON."""
    click.echo(json.dumps(_detect_inspect(path), indent=2, sort_keys=True))


@main.command("simulate")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--policy",
    "policy_name",
    type=click.Choice(["default", "pdf", "office", "audio"], case_sensitive=False),
    default="default",
    show_default=True,
)
@click.option("--bucket", default="simulate", show_default=True)
@click.option("--object-name", default=None, help="Defaults to the file basename.")
@click.option("--json", "as_json", is_flag=True)
def simulate_cmd(
    path: Path,
    policy_name: str,
    bucket: str,
    object_name: str | None,
    as_json: bool,
) -> None:
    """Dry-run upload against FakeStorageProvider."""
    extras: tuple[str, ...] = ()
    if policy_name != "default":
        extras = (policy_name,)
    try:
        policy = _build_policy(extras, max_size=50 * 1024 * 1024)
    except ImportError as exc:
        raise click.ClickException(str(exc)) from exc

    storage = FakeStorageProvider()
    uploader = Uploader(policy, storage)
    key = object_name or path.name
    try:
        result = uploader.upload(
            make_upload_file(_read_path(path), name=path.name),
            bucket=bucket,
            object_name=key,
        )
    except UploaderError as exc:
        if as_json:
            click.echo(json.dumps({"ok": False, "error": str(exc)}))
        else:
            click.echo(f"FAIL: {exc}", err=True)
        sys.exit(1)

    payload = {
        "ok": True,
        "bucket": bucket,
        "object_name": key,
        "etag": result.etag,
        "stored_objects": len(storage.objects),
        "bytes": len(storage.objects[0].body) if storage.objects else 0,
    }
    if as_json:
        click.echo(json.dumps(payload))
    else:
        click.echo(
            f"OK: simulated put s3://{bucket}/{key} "
            f"({payload['bytes']} bytes, etag={result.etag})"
        )


@main.group("policies")
def policies_group() -> None:
    """Built-in policy presets."""


@policies_group.command("list")
@click.option("--json", "as_json", is_flag=True)
def policies_list(as_json: bool) -> None:
    """Show available policy presets."""
    presets = [
        {
            "name": "default",
            "package": "uploadkit-security",
            "description": "Size/extension/MIME/filename/checksum stack",
        },
        {
            "name": "pdf",
            "package": "uploadkit-pdf",
            "description": "Safe PDF (no JS/embeds/encryption)",
        },
        {
            "name": "office",
            "package": "uploadkit-office",
            "description": "OOXML/ODF (no macros/external links)",
        },
        {
            "name": "audio",
            "package": "uploadkit-audio",
            "description": "Audio codec/duration limits",
        },
    ]
    if as_json:
        click.echo(json.dumps(presets, indent=2))
        return
    for item in presets:
        click.echo(f"{item['name']:8}  {item['package']:20}  {item['description']}")


@main.command("doctor")
@click.option("--json", "as_json", is_flag=True)
def doctor_cmd(as_json: bool) -> None:
    """Check optional extras and system dependencies."""
    checks: dict[str, Any] = {}

    def _try(label: str, import_name: str) -> None:
        try:
            __import__(import_name)
            checks[label] = {"ok": True}
        except ImportError as exc:
            checks[label] = {"ok": False, "error": str(exc)}

    _try("uploadkit", "uploadkit")
    _try("uploadkit-security", "uploadkit_security")
    _try("uploadkit-testing", "uploadkit_testing")
    _try("uploadkit-pdf", "uploadkit_pdf")
    _try("uploadkit-office", "uploadkit_office")
    _try("uploadkit-audio", "uploadkit_audio")

    try:
        import magic  # type: ignore[import-untyped]

        checks["libmagic"] = {"ok": True, "version": getattr(magic, "__version__", None)}
    except ImportError as exc:
        checks["libmagic"] = {"ok": False, "error": str(exc)}

    try:
        import shutil

        clam = shutil.which("clamscan") or shutil.which("clamdscan")
        checks["clamav"] = {"ok": clam is not None, "path": clam}
    except Exception as exc:  # noqa: BLE001
        checks["clamav"] = {"ok": False, "error": str(exc)}

    if as_json:
        click.echo(json.dumps(checks, indent=2))
        return
    for name, info in checks.items():
        status = "OK" if info.get("ok") else "MISSING"
        detail = ""
        if not info.get("ok") and info.get("error"):
            detail = f" ({info['error']})"
        elif info.get("path"):
            detail = f" ({info['path']})"
        click.echo(f"{name:22} {status}{detail}")


if __name__ == "__main__":
    main()
