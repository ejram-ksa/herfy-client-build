from __future__ import annotations

from source_manifest import verify_source_metadata


def main() -> int:
    manifest = verify_source_metadata()
    validation = manifest.get("source_validation") or {}
    pytest_result = validation.get("pytest") or {}
    print(
        "HERFY_SOURCE_MANIFEST_OK "
        f"files={manifest['file_count']} "
        f"python_files={manifest['python_file_count']} "
        f"pytest_passed={pytest_result.get('passed')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
