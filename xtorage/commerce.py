from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import httpx

from .codec import decode_frames, decode_image_auto


QUERY_IDS = {
    "create_catalog": ("ZE1ktBqoLAal6Evb2pUs_A", "CreateProductCatalogMutation"),
    "delete_catalog": ("fpSaQs7IVE3Y6aj11mLsog", "DeleteCatalogMutation"),
    "upload_products": ("CoScZSo_RtQvqhneFUT6lA", "UploadProductsMutation"),
    "search_product": ("ueNqJSt7CqADeNFbWYl8hw", "GetSearchedProductQuery"),
    "product_details": ("-bahyx0GrJXPyQSGLrLjKg", "GetProductDetailsQuery"),
    "delete_products": ("bCRsbx8kwXhhmZy00Wb0vA", "DeleteProductsMutation"),
}


@dataclass
class Account:
    owner_id: str
    bearer: str
    cookies: dict[str, str]
    label: str = "account"

    @property
    def ct0(self) -> str:
        return self.cookies["ct0"]


def load_account(path: Path) -> Account:
    if str(path) == "-":
        raw = os.environ.get("XTORAGE_ACCOUNT_JSON")
        if not raw:
            raise ValueError("XTORAGE_ACCOUNT_JSON is required when --account - is used")
        data = json.loads(raw)
    else:
        data = json.loads(path.read_text(encoding="utf-8"))

    env_bearer = os.environ.get("XTORAGE_BEARER", "")
    if isinstance(data, list):
        cookies = {item["name"]: item["value"] for item in data if item.get("name") and isinstance(item.get("value"), str)}
        owner_id = data[0].get("owner_id", "") if data and isinstance(data[0], dict) else ""
        bearer = env_bearer
        label = "chrome-cookie-export"
    else:
        cookies = data.get("cookies") or {}
        if data.get("chrome_cookie_export"):
            export = json.loads(Path(data["chrome_cookie_export"]).read_text(encoding="utf-8"))
            cookies.update({item["name"]: item["value"] for item in export if item.get("name") and isinstance(item.get("value"), str)})
        owner_id = data.get("owner_id") or ""
        bearer = data.get("bearer") or env_bearer
        label = data.get("label") or "account"

    if not owner_id and "twid" in cookies:
        match = re.search(r"\d+", unquote(cookies["twid"]))
        owner_id = match.group(0) if match else ""
    if not bearer:
        raise ValueError("account JSON must provide bearer")
    for required in ("auth_token", "ct0"):
        if required not in cookies:
            raise ValueError(f"account JSON/cookie export missing {required}")
    if not owner_id:
        raise ValueError("account JSON must provide owner_id or twid cookie")
    return Account(owner_id=owner_id, bearer=bearer, cookies=cookies, label=label)


def cookie_header(cookies: dict[str, str]) -> str:
    keep = [
        "auth_token",
        "ct0",
        "twid",
        "auth_multi",
        "guest_id",
        "guest_id_ads",
        "guest_id_marketing",
        "personalization_id",
        "ads_prefs",
        "__cf_bm",
    ]
    return "; ".join(f"{key}={cookies[key]}" for key in keep if cookies.get(key))


def redact(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    text = text.replace("auth_token=", "auth_token=<redacted>")
    text = text.replace("ct0=", "ct0=<redacted>")
    return text[:700]


class CommerceClient:
    def __init__(self, account: Account, timeout: float = 60.0) -> None:
        self.account = account
        self.client = httpx.Client(timeout=timeout, http2=True)

    def close(self) -> None:
        self.client.close()

    def gql(self, key: str, variables: dict[str, Any]) -> dict[str, Any]:
        query_id, op = QUERY_IDS[key]
        response = self.client.post(
            f"https://x.com/i/api/graphql/{query_id}/{op}",
            headers={
                "authorization": f"Bearer {self.account.bearer}",
                "content-type": "application/json",
                "x-csrf-token": self.account.ct0,
                "x-twitter-active-user": "yes",
                "x-twitter-auth-type": "OAuth2Session",
                "user-agent": "Mozilla/5.0",
                "cookie": cookie_header(self.account.cookies),
            },
            json={"variables": variables, "queryId": query_id},
        )
        try:
            body = response.json()
        except Exception:
            body = {"parse_error": response.text[:300]}
        if response.status_code in (401, 403):
            raise RuntimeError(f"auth stop {response.status_code}: {redact(body)}")
        if any(error.get("code") in (32, 64) for error in body.get("errors", [])):
            raise RuntimeError(f"auth/automation stop: {redact(body.get('errors'))}")
        return {"status": response.status_code, "json": body}

    def create_catalog(self, name: str) -> str:
        result = self.gql("create_catalog", {"catalog_name": name[:48], "owner_id": self.account.owner_id})
        catalog = result["json"].get("data", {}).get("create_commerce_catalog")
        if not catalog or not catalog.get("rest_id"):
            raise RuntimeError(f"could not create catalog: {redact(result['json'])}")
        return catalog["rest_id"]

    def upload_products(self, catalog_id: str, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = self.gql("upload_products", {"catalog_id": catalog_id, "product_data": products})
        payload = result["json"].get("data", {}).get("upload_products") or {}
        return payload.get("products_results") or []

    def search_product(self, catalog_id: str, product_id: str) -> dict[str, Any] | None:
        result = self.gql("search_product", {"catalog_id": catalog_id, "product_id": product_id})
        return result["json"].get("data", {}).get("commerce_catalog_by_rest_id", {}).get("commerce_product_by_product_id")

    def delete_catalog(self, catalog_id: str) -> None:
        self.gql("delete_catalog", {"catalog_id": catalog_id})

    def delete_products(self, product_keys: list[str]) -> None:
        if product_keys:
            self.gql("delete_products", {"product_keys": product_keys})


def product_payload(product_id: str, title: str, image_url: str) -> dict[str, Any]:
    return {
        "product_id": product_id,
        "title": title[:150],
        "description": f"Xtorage chunk {product_id}",
        "brand": "xtorage",
        "link": f"https://example.com/xtorage/{product_id}",
        "price": {"currency_code": "Usd", "micro_value": "1000000", "value": 1},
        "availability": "InStock",
        "condition": "New",
        "inventory": 1,
        "image": {"image_url": image_url},
    }


def upload_manifest(
    *,
    account_path: Path,
    manifest_path: Path,
    public_base_url: str,
    catalog_id: str | None = None,
    poll_count: int = 18,
    poll_delay: float = 10.0,
    cleanup: bool = False,
    output_path: Path | None = None,
) -> dict[str, Any]:
    account = load_account(account_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    public_base = public_base_url.rstrip("/")
    client = CommerceClient(account)
    created_catalog = False
    product_keys: list[str] = []
    try:
        if catalog_id is None:
            catalog_id = client.create_catalog(f"xtorage-{manifest['file_id'][:12]}")
            created_catalog = True

        products = []
        for chunk in manifest["chunks"]:
            image_url = f"{public_base}/{quote(chunk['filename'])}"
            products.append(product_payload(chunk["product_id"], f"xtorage {manifest['file_id'][:8]} chunk {chunk['index']}", image_url))

        upload_results = client.upload_products(catalog_id, products)
        for item in upload_results:
            if item.get("product_key"):
                product_keys.append(item["product_key"])

        statuses = []
        for chunk in manifest["chunks"]:
            product = None
            for poll in range(poll_count):
                if poll:
                    time.sleep(poll_delay)
                product = client.search_product(catalog_id, chunk["product_id"])
                validity = product.get("product_validity", {}).get("status") if product else None
                if validity in ("Valid", "Invalid"):
                    break
            statuses.append({"index": chunk["index"], "product_id": chunk["product_id"], "product": sanitize_product(product)})

        result = {
            "version": 1,
            "catalog_id": catalog_id,
            "created_catalog": created_catalog,
            "file_id": manifest["file_id"],
            "input_filename": manifest["input_filename"],
            "chunks": statuses,
            "product_keys": product_keys,
            "cleanup": cleanup,
        }
        if cleanup:
            client.delete_products(product_keys)
            if created_catalog:
                client.delete_catalog(catalog_id)
        if output_path:
            output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        client.close()


def sanitize_product(product: dict[str, Any] | None) -> dict[str, Any] | None:
    if not product:
        return None
    urls: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str) and value.startswith("https://pbs.twimg.com/commerce_product_img"):
            urls.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(product)
    core = product.get("product_core_data", {})
    return {
        "validity": product.get("product_validity", {}).get("status"),
        "product_key": core.get("product_metadata", {}).get("product_key"),
        "title": core.get("product_details", {}).get("title"),
        "rehost_urls": sorted(set(urls)),
        "source_sha256": hashlib.sha256(json.dumps(product, sort_keys=True, default=str).encode()).hexdigest(),
    }


def retrieve_upload_result(upload_result_path: Path, out_path: Path | None = None, download_dir: Path | None = None) -> dict[str, Any]:
    result = json.loads(upload_result_path.read_text(encoding="utf-8"))
    uploaded = result.get("uploaded", result)
    encoded = result.get("encoded", {})
    chunks = uploaded.get("chunks") or []
    if not chunks:
        raise ValueError("upload result has no chunks")

    base_dir = download_dir or upload_result_path.with_suffix("").parent / f"{upload_result_path.stem}_downloaded"
    base_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    downloads = []

    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        for chunk in sorted(chunks, key=lambda item: item.get("index", 0)):
            product = chunk.get("product") or {}
            urls = product.get("rehost_urls") or []
            if not urls:
                raise ValueError(f"chunk {chunk.get('index')} has no rehost URL")
            url = urls[0]
            response = client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            ext = ".jpg" if "jpeg" in content_type else ".png" if "png" in content_type else ".bin"
            path = base_dir / f"chunk-{int(chunk.get('index', 0)):04d}{ext}"
            path.write_bytes(response.content)
            frame = decode_image_auto(path)
            frames.append(frame)
            downloads.append(
                {
                    "index": chunk.get("index"),
                    "url": url,
                    "path": str(path),
                    "content_type": content_type,
                    "size": len(response.content),
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                    "mode": frame.mode_name,
                }
            )

    output = out_path or Path(uploaded.get("input_filename") or encoded.get("input_filename") or "xtorage-retrieved.bin")
    decoded = decode_frames(frames, output)
    decoded["downloads"] = downloads
    return decoded
