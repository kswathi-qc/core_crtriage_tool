#!/usr/bin/env python3
"""Orbit Web API client using the local Kerberos auth-file pattern."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

try:
    import kerberos  # type: ignore
    import requests
    import urllib3
except ImportError as exc:  # pragma: no cover - exercised only on incomplete hosts.
    kerberos = None  # type: ignore
    requests = None  # type: ignore
    urllib3 = None  # type: ignore
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AUTH_FILE = ROOT / "auth" / "orbit_auth.txt"


class OrbitApi:
    def __init__(
        self,
        server: str = "orbit-sd",
        auth_file: Path | None = None,
        renew_krb_token: bool = True,
    ) -> None:
        if IMPORT_ERROR is not None:
            raise RuntimeError(
                "Orbit Web API access requires the Python packages 'requests', "
                "'urllib3', and 'kerberos'."
            ) from IMPORT_ERROR

        self.server = server
        self.auth_file = auth_file or default_auth_file()
        self.user = ""
        self.realm = ""
        self.password = ""
        self.application_source = ""
        self.impersonated_username = ""
        self.authenticate()
        if renew_krb_token:
            self.generate_kerberos_token()

    def authenticate(self) -> None:
        try:
            lines = self.auth_file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise RuntimeError(f"Unable to read Orbit auth file: {self.auth_file}") from exc

        if len(lines) < 4:
            raise RuntimeError(
                f"Invalid Orbit auth file: {self.auth_file}. Expected at least 4 lines."
            )
        self.user = lines[0].strip()
        self.realm = lines[1].strip()
        self.password = lines[2].rstrip("\n")
        self.application_source = lines[3].strip()
        self.impersonated_username = lines[4].strip() if len(lines) > 4 else ""

    def generate_kerberos_token(self) -> None:
        proc = subprocess.run(
            ["/usr/bin/kinit", f"{self.user}@{self.realm}"],
            input=f"{self.password}\n",
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"kinit failed for Orbit service account: {proc.stderr.strip()}")

    def call(
        self,
        endpoint: str,
        method: str = "get",
        data: dict[str, Any] | list[Any] | None = None,
        timeout: int = 120,
    ) -> Any:
        _, krb_context = kerberos.authGSSClientInit(f"HTTP@{self.server}")
        kerberos.authGSSClientStep(krb_context, "")
        headers = {
            "Authorization": "Negotiate " + kerberos.authGSSClientResponse(krb_context),
            "ApplicationSource": self.application_source,
            "Content-Type": "application/json",
        }
        if self.impersonated_username:
            headers["ImpersonatedUserName"] = self.impersonated_username

        url = f"https://{self.server}/api/{endpoint.lstrip('/')}"
        response = requests.request(
            method,
            url,
            data=json.dumps(data or {}),
            headers=headers,
            verify=False,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("IsSuccess"):
            return payload.get("Content")
        if isinstance(payload, dict):
            raise RuntimeError(json.dumps(payload.get("Errors", payload), indent=2))
        return payload

    def call_first(
        self,
        attempts: list[tuple[str, str, dict[str, Any] | list[Any] | None]],
        timeout: int = 120,
    ) -> Any:
        errors = []
        for endpoint, method, data in attempts:
            try:
                return self.call(endpoint, method=method, data=data, timeout=timeout)
            except Exception as exc:
                errors.append(f"{method.upper()} {endpoint}: {exc}")
        raise RuntimeError("Orbit API call failed for all endpoint candidates:\n" + "\n".join(errors))

    def run_saved_query(self, query_id: str, page_size: int = 100000, timeout: int = 120) -> dict[str, Any]:
        content = self.call_first(
            [
                (f"query/run/{query_id}?pageSize={page_size}", "post", None),
                (f"query/{query_id}/run?pageSize={page_size}", "post", None),
            ],
            timeout=timeout,
        )
        if not isinstance(content, dict):
            raise RuntimeError(f"Unexpected saved-query response shape: {type(content).__name__}")
        return content

    def get_cr_details(self, cr_number: str, timeout: int = 120) -> dict[str, Any]:
        content = self.call_first(
            [
                (f"changeRequest/{cr_number}", "get", None),
                (f"cr/{cr_number}", "get", None),
            ],
            timeout=timeout,
        )
        if not isinstance(content, dict):
            raise RuntimeError(f"Unexpected CR detail response for {cr_number}: {type(content).__name__}")
        return content

    def get_cr_comments(self, cr_number: str, timeout: int = 120) -> list[Any]:
        content = self.call_first(
            [
                (f"changeRequest/{cr_number}/comments", "get", None),
                (f"changeRequest/{cr_number}/comment", "get", None),
                (f"cr/{cr_number}/comments", "get", None),
            ],
            timeout=timeout,
        )
        if isinstance(content, list):
            return content
        if isinstance(content, dict):
            for key in ("Results", "Comments", "Items"):
                value = content.get(key)
                if isinstance(value, list):
                    return value
        raise RuntimeError(f"Unexpected CR comments response for {cr_number}: {type(content).__name__}")

    def add_tags(self, cr_number: str, tags: list[str], timeout: int = 120) -> Any:
        payloads = [
            {"ChangeRequestNumber": cr_number, "Tags": tags},
            {"crId": cr_number, "tags": tags},
            {"tags": tags},
        ]
        attempts = []
        for payload in payloads:
            attempts.extend(
                [
                    (f"changeRequest/{cr_number}/tags", "post", payload),
                    (f"changeRequest/{cr_number}/tag", "post", payload),
                    ("changeRequest/tags", "post", payload),
                ]
            )
        return self.call_first(attempts, timeout=timeout)

    def update_cr_details(self, cr_number: str, fields: dict[str, Any], timeout: int = 120) -> Any:
        payload = {"ChangeRequestNumber": cr_number, **fields}
        return self.call_first(
            [
                (f"changeRequest/{cr_number}", "patch", payload),
                (f"changeRequest/{cr_number}", "put", payload),
                ("changeRequest", "patch", payload),
                ("changeRequest", "put", payload),
            ],
            timeout=timeout,
        )

    def add_cr_comment(self, cr_number: str, comment_text: str, timeout: int = 120) -> Any:
        payloads = [
            {"ChangeRequestNumber": cr_number, "CommentText": comment_text},
            {"changeRequestNumber": cr_number, "commentText": comment_text},
            {"commentText": comment_text},
            {"Text": comment_text},
        ]
        attempts = []
        for payload in payloads:
            attempts.extend(
                [
                    (f"changeRequest/{cr_number}/comments", "post", payload),
                    (f"changeRequest/{cr_number}/comment", "post", payload),
                    ("changeRequest/comment", "post", payload),
                ]
            )
        return self.call_first(attempts, timeout=timeout)


def default_auth_file() -> Path:
    return DEFAULT_AUTH_FILE
