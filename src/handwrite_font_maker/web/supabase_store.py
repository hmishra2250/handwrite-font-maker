from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol
from urllib.parse import quote


class ObjectStore(Protocol):
    def signed_upload_url(self, object_key: str) -> str: ...
    def signed_download_url(self, object_key: str, expires_in: int = 1800) -> str: ...
    def download_to_path(self, object_key: str, destination: Path) -> None: ...
    def upload_from_path(self, object_key: str, source: Path, content_type: str) -> None: ...


class SupabaseStorage:
    """Supabase Storage adapter used by Render API and worker services."""

    def __init__(self, *, url: str | None = None, service_key: str | None = None, bucket: str | None = None) -> None:
        self.url = (url or os.environ.get("SUPABASE_URL") or "").rstrip("/")
        self.service_key = service_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
        self.bucket = bucket or os.environ.get("SUPABASE_STORAGE_BUCKET") or "handwrite-font-jobs"
        if not self.url or not self.service_key:
            raise RuntimeError("Supabase storage is not configured.")

    @property
    def _headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.service_key}", "apikey": self.service_key}

    def signed_upload_url(self, object_key: str) -> str:
        import requests

        encoded = quote(object_key, safe="/")
        response = requests.post(f"{self.url}/storage/v1/object/upload/sign/{self.bucket}/{encoded}", headers=self._headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        signed = data.get("signedURL") or data.get("signedUrl") or data.get("url")
        if not signed:
            raise RuntimeError("Supabase did not return a signed upload URL.")
        return str(signed if str(signed).startswith("http") else f"{self.url}{signed}")

    def signed_download_url(self, object_key: str, expires_in: int = 1800) -> str:
        import requests

        encoded = quote(object_key, safe="/")
        response = requests.post(
            f"{self.url}/storage/v1/object/sign/{self.bucket}/{encoded}",
            headers={**self._headers, "content-type": "application/json"},
            json={"expiresIn": expires_in},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        signed = data.get("signedURL") or data.get("signedUrl") or data.get("url")
        if not signed:
            raise RuntimeError("Supabase did not return a signed download URL.")
        return str(signed if str(signed).startswith("http") else f"{self.url}{signed}")

    def download_to_path(self, object_key: str, destination: Path) -> None:
        import requests

        encoded = quote(object_key, safe="/")
        response = requests.get(f"{self.url}/storage/v1/object/{self.bucket}/{encoded}", headers=self._headers, timeout=120)
        response.raise_for_status()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)

    def upload_from_path(self, object_key: str, source: Path, content_type: str) -> None:
        import requests

        encoded = quote(object_key, safe="/")
        with source.open("rb") as handle:
            response = requests.post(
                f"{self.url}/storage/v1/object/{self.bucket}/{encoded}",
                params={"upsert": "true"},
                headers={**self._headers, "content-type": content_type},
                data=handle,
                timeout=120,
            )
        response.raise_for_status()


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, object_key: str) -> Path:
        safe = Path(object_key)
        if safe.is_absolute() or ".." in safe.parts:
            raise ValueError("Unsafe object key")
        return self.root / safe

    def signed_upload_url(self, object_key: str) -> str:
        return f"local://upload/{object_key}"

    def signed_download_url(self, object_key: str, expires_in: int = 1800) -> str:
        return f"local://download/{object_key}?expiresIn={expires_in}"

    def download_to_path(self, object_key: str, destination: Path) -> None:
        source = self._path(object_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())

    def upload_from_path(self, object_key: str, source: Path, content_type: str) -> None:
        target = self._path(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
