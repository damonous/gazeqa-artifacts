"""Site discovery helpers using Playwright capture."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from .exploration import PageDescriptor
from .models import CreateRunPayload
from .site_map import build_default_site_map
from .path_utils import resolve_run_path

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import guard
    from playwright.sync_api import (  # type: ignore
        TimeoutError as PlaywrightTimeoutError,
        sync_playwright as _sync_playwright,
    )
except Exception:  # pragma: no cover - environment without Playwright
    PlaywrightTimeoutError = Exception  # type: ignore
    _sync_playwright = None


@dataclass(slots=True)
class DiscoveryConfig:
    """Configuration for live site discovery."""

    storage_root: Path
    max_pages: int = 5
    link_selectors: Sequence[str] = (
        "nav a[href]",
        "header a[href]",
        "main a[href]",
        "a[href*='admin']",
    )
    screenshot_dir: str = "capture/screenshots"
    dom_dir: str = "capture/dom"
    wait_for: str = "networkidle"
    timeout_ms: int = 15000


class SiteDiscoveryError(RuntimeError):
    """Raised when live site discovery fails irrecoverably."""


def discover_site_map(
    run_id: str,
    payload: CreateRunPayload,
    storage_root: Path | str,
    *,
    config: DiscoveryConfig | None = None,
) -> Tuple[List[PageDescriptor], Dict[str, List[PageDescriptor]]]:
    """Discover site map using Playwright with graceful fallback."""

    discovery_config = config or DiscoveryConfig(storage_root=Path(storage_root))
    storage_root_path = discovery_config.storage_root

    if payload.target_url.lower().startswith("http") is False:
        logger.warning("Target URL %s is not HTTP(S); using default site map", payload.target_url)
        return build_default_site_map(run_id, payload, storage_root_path)

    try:
        return _discover_with_playwright(run_id, payload, discovery_config)
    except SiteDiscoveryError:
        logger.exception("Site discovery failed; falling back to default map")
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected error during site discovery: %s", exc)
    return build_default_site_map(run_id, payload, storage_root_path)


def _discover_with_playwright(
    run_id: str,
    payload: CreateRunPayload,
    config: DiscoveryConfig,
) -> Tuple[List[PageDescriptor], Dict[str, List[PageDescriptor]]]:
    if _sync_playwright is None:  # pragma: no cover - environment guard
        raise SiteDiscoveryError("Playwright runtime not available")

    run_root = resolve_run_path(config.storage_root, run_id)
    screenshot_root = run_root / config.screenshot_dir
    dom_root = run_root / config.dom_dir
    screenshot_root.mkdir(parents=True, exist_ok=True)
    dom_root.mkdir(parents=True, exist_ok=True)

    base_url = payload.target_url.rstrip("/")
    parsed_base = urlparse(base_url)
    allow_netloc = parsed_base.netloc

    descriptors: List[PageDescriptor] = []
    adjacency: Dict[str, List[PageDescriptor]] = {}
    seen_urls: set[str] = set()
    assigned_ids: set[str] = set()

    def classify_section(url: str) -> str:
        lower = url.lower()
        if any(token in lower for token in ("admin", "settings", "config")):
            return "admin"
        if any(token in lower for token in ("team", "people")):
            return "team"
        if "about" in lower:
            return "mission"
        return "mission"

    def derive_page_id(url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if not path:
            slug = "home"
        else:
            slug = path.replace("/", "-")
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in slug)
        cleaned = cleaned.strip("-") or "page"
        candidate = cleaned
        index = 1
        while candidate in assigned_ids:
            index += 1
            candidate = f"{cleaned}-{index}"
        assigned_ids.add(candidate)
        return candidate

    def record_descriptor(url: str, title: str, page_id: str, dom: str, screenshot_bytes: bytes) -> PageDescriptor:
        screenshot_path = (screenshot_root / f"{page_id}.png")
        dom_path = (dom_root / f"{page_id}.html")
        screenshot_path.write_bytes(screenshot_bytes)
        dom_path.write_text(dom, encoding="utf-8")
        descriptor = PageDescriptor(
            url=url,
            title=title or url,
            section=classify_section(url),
            page_id=page_id,
            screenshot=screenshot_path.relative_to(run_root).as_posix(),
            dom_snapshot=dom_path.relative_to(run_root).as_posix(),
        )
        descriptors.append(descriptor)
        adjacency.setdefault(page_id, [])
        return descriptor

    def extract_links(page) -> List[str]:  # type: ignore[no-untyped-def]
        selector_script = """
        (selectors) => {
            const unique = new Set();
            const urls = [];
            for (const selector of selectors) {
                for (const el of document.querySelectorAll(selector)) {
                    if (!el || !el.href) continue;
                    urls.push(el.href);
                }
            }
            return urls;
        }
        """
        try:
            results = page.eval_on_selector_all("body", selector_script, list(config.link_selectors))
        except Exception:
            results = []
        cleaned: List[str] = []
        for href in results:
            if not isinstance(href, str):
                continue
            href = href.strip()
            if not href or href.startswith("javascript:"):
                continue
            parsed = urlparse(href)
            if parsed.scheme not in {"http", "https"}:
                continue
            netloc = parsed.netloc or allow_netloc
            if netloc != allow_netloc:
                continue
            normalized = urljoin(base_url + "/", parsed.path or "/")
            if normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            cleaned.append(normalized)
        return cleaned

    try:
        with _sync_playwright() as playwright:
            browser_type = playwright.chromium
            browser = browser_type.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            try:
                page.goto(base_url, wait_until=config.wait_for, timeout=config.timeout_ms)
            except PlaywrightTimeoutError as exc:
                raise SiteDiscoveryError(f"Timed out reaching {base_url}: {exc}") from exc

            root_id = derive_page_id(base_url)
            dom = page.content()
            screenshot_bytes = page.screenshot(full_page=True)
            root_descriptor = record_descriptor(base_url, page.title(), root_id, dom, screenshot_bytes)

            seen_urls.add(base_url)

            candidate_links = extract_links(page)
            limit = max(0, config.max_pages - 1)
            candidate_links = candidate_links[:limit]

            for link in candidate_links:
                page_id = derive_page_id(link)
                child_page = context.new_page()
                try:
                    child_page.goto(link, wait_until=config.wait_for, timeout=config.timeout_ms)
                except PlaywrightTimeoutError:
                    child_page.close()
                    logger.warning("Timed out capturing %s", link)
                    continue
                dom = child_page.content()
                screenshot_bytes = child_page.screenshot(full_page=True)
                descriptor = record_descriptor(link, child_page.title(), page_id, dom, screenshot_bytes)
                adjacency[root_id].append(descriptor)
                adjacency.setdefault(page_id, [])
                child_page.close()

            browser.close()
    except PlaywrightTimeoutError as exc:  # pragma: no cover - double guard
        raise SiteDiscoveryError(f"Site discovery timeout: {exc}") from exc
    except SiteDiscoveryError:
        raise
    except Exception as exc:
        raise SiteDiscoveryError(f"Site discovery failed: {exc}") from exc

    if not descriptors:
        raise SiteDiscoveryError("No pages discovered")

    return descriptors, adjacency


__all__ = ["discover_site_map", "DiscoveryConfig", "SiteDiscoveryError"]
