from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from build.release.verify_deployed_release import (
    ReleaseVerificationError,
    _descriptor,
    _origin,
    verify_deployed_release,
)


@contextmanager
def _release_server(*, package_available: bool = True):
    version = "2.18.1"
    package_name = f"HerfyClient_Setup_{version}.exe"
    package = (b"MZ" + bytes(range(256))) * 64
    digest = hashlib.sha256(package).hexdigest()
    metadata = {
        "latest": version,
        "version": version,
        "latest_version": version,
        "target_version": version,
        "available": True,
        "update_available": True,
        "mandatory": True,
        "force_update": True,
        "current_supported": False,
        "package_name": package_name,
        "setup_package": package_name,
        "url": f"/updates/packages/{package_name}",
        "installer_url": f"/updates/packages/{package_name}",
        "download_url": f"/updates/packages/{package_name}",
        "sha256": digest,
        "setup_sha256": digest,
        "size": len(package),
        "setup_size": len(package),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/":
                body = (
                    f"<html><body>{version} "
                    f'<a href="/updates/packages/{package_name}">{package_name}</a>'
                    "</body></html>"
                ).encode()
                self._send(200, body, "text/html; charset=utf-8")
                return
            if path in {
                "/updates/latest.json",
                "/updates/manifest.json",
                "/updates/upgrade-plan.json",
            }:
                self._send(200, json.dumps(metadata).encode(), "application/json")
                return
            if path == "/api/health":
                self._send(
                    200,
                    json.dumps({"status": "ok", "version": version}).encode(),
                    "application/json",
                )
                return
            if path == "/api/meta/client-bootstrap":
                self._send(
                    200,
                    json.dumps({"upgrade_plan": metadata}).encode(),
                    "application/json",
                )
                return
            if path == f"/updates/packages/{package_name}" and package_available:
                self._send(200, package, "application/octet-stream")
                return
            self._send(404, b"not found", "text/plain")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        yield base, metadata, package
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_deployed_release_verifier_checks_metadata_api_homepage_and_binary():
    with _release_server() as (base, metadata, package):
        report = verify_deployed_release(
            base_url=base,
            api_base_url=f"{base}/api",
            expected_version=metadata["version"],
            timeout=5,
            maximum_artifact_bytes=len(package) + 1,
        )
    assert report.status == "ok"
    assert report.artifact == {
        "downloaded": True,
        "size": len(package),
        "sha256": hashlib.sha256(package).hexdigest(),
    }
    assert report.api["homepage"]["package_present"] is True
    assert report.api["server"]["upgrade_plan_present"] is True
    assert len(report.descriptors) == 3


def test_deployed_release_verifier_rejects_missing_installer():
    with _release_server(package_available=False) as (base, metadata, package):
        with pytest.raises(ReleaseVerificationError, match="HTTP 404"):
            verify_deployed_release(
                base_url=base,
                api_base_url=f"{base}/api",
                expected_version=metadata["version"],
                timeout=5,
                maximum_artifact_bytes=len(package) + 1,
            )


def test_deployed_release_verifier_rejects_cross_origin_package_url():
    payload = {
        "version": "2.18.1",
        "available": True,
        "update_available": True,
        "mandatory": True,
        "force_update": True,
        "current_supported": False,
        "package_name": "HerfyClient_Setup_2.18.1.exe",
        "url": "https://example.invalid/updates/packages/HerfyClient_Setup_2.18.1.exe",
        "sha256": "a" * 64,
        "size": 100,
    }
    with pytest.raises(ReleaseVerificationError, match="changed origin"):
        _descriptor(
            payload,
            source="latest.json",
            expected_version="2.18.1",
            base_url="https://herfy.online",
        )


def test_deployed_release_verifier_rejects_encoded_package_path_traversal():
    payload = {
        "version": "2.18.1",
        "available": True,
        "update_available": True,
        "mandatory": False,
        "force_update": False,
        "current_supported": True,
        "package_name": "HerfyClient_Setup_2.18.1.exe",
        "url": "/updates/packages/%2e%2e/HerfyClient_Setup_2.18.1.exe",
        "sha256": "a" * 64,
        "size": 100,
    }
    with pytest.raises(ReleaseVerificationError, match="approved update package path"):
        _descriptor(
            payload,
            source="latest.json",
            expected_version="2.18.1",
            base_url="https://herfy.online",
        )


def test_deployed_release_origin_normalizes_default_ports():
    assert _origin("https://herfy.online/path") == _origin(
        "https://herfy.online:443/other"
    )
    assert _origin("http://127.0.0.1/path") == _origin(
        "http://127.0.0.1:80/other"
    )

def test_deployed_release_verifier_accepts_optional_production_policy():
    payload = {
        "version": "2.18.1",
        "available": True,
        "update_available": True,
        "mandatory": False,
        "force_update": False,
        "current_supported": True,
        "package_name": "HerfyClient_Setup_2.18.1.exe",
        "url": "/updates/packages/HerfyClient_Setup_2.18.1.exe",
        "sha256": "a" * 64,
        "size": 100,
    }
    descriptor = _descriptor(
        payload,
        source="latest.json",
        expected_version="2.18.1",
        base_url="https://herfy.online",
    )
    assert descriptor.mandatory is False
    assert descriptor.current_supported is True


def test_deployed_release_verifier_rejects_inconsistent_update_policy():
    payload = {
        "version": "2.18.1",
        "available": True,
        "update_available": True,
        "mandatory": False,
        "force_update": True,
        "current_supported": True,
        "package_name": "HerfyClient_Setup_2.18.1.exe",
        "url": "/updates/packages/HerfyClient_Setup_2.18.1.exe",
        "sha256": "a" * 64,
        "size": 100,
    }
    with pytest.raises(ReleaseVerificationError, match="force_update does not match"):
        _descriptor(
            payload,
            source="latest.json",
            expected_version="2.18.1",
            base_url="https://herfy.online",
        )

