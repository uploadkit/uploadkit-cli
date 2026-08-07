# uploadkit-cli

[![CI](https://github.com/uploadkit/uploadkit-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/uploadkit/uploadkit-cli/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](pyproject.toml)

Developer CLI for UploadKit validation, inspection, and upload simulation.

## What problem does this solve?

A local debug surface for composing Core + security + feature-package validators
without writing app code.

## When to use it

Use during development and CI to lint fixture uploads.

## When not to use it

- Do not expose framework HTTP APIs here.
- Do not use as a production upload gateway.

## Installation

```bash
pip install uploadkit-cli

# Optional feature packages
pip install 'uploadkit-cli[pdf,office,audio]'
# or
pip install 'uploadkit-cli[all]'
```

## Commands

```bash
uploadkit validate path/to/file.pdf -e pdf
uploadkit inspect path/to/file.docx
uploadkit simulate path/to/file.wav --policy audio --json
uploadkit policies list
uploadkit doctor
```

Exit code `1` on validation failure (CI-friendly with `--json`).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
