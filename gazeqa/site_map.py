"""Default site map and adjacency builders for demo workflows."""
from __future__ import annotations

from typing import Dict, List, Tuple
from urllib.parse import urljoin

from .exploration import PageDescriptor
from .models import CreateRunPayload


def build_default_site_map(payload: CreateRunPayload) -> Tuple[List[PageDescriptor], Dict[str, List[PageDescriptor]]]:
    """Return a deterministic mission/team/admin site map for prototype runs."""

    base = payload.target_url.rstrip("/")
    if not base:
        base = "https://example.test"

    def page(page_id: str, path: str, title: str, section: str) -> PageDescriptor:
        url = urljoin(base + "/", path.lstrip("/"))
        return PageDescriptor(page_id=page_id, url=url, title=title, section=section)

    home = page("home", "/", "Mission Control", "mission")
    about = page("about", "about", "About", "mission")
    team = page("team", "team", "Team", "mission")
    admin = page("admin", "admin", "Admin", "admin")
    settings = page("settings", "admin/settings", "Admin Settings", "admin")

    site_map = [home, about, team, admin, settings]
    adjacency = {
        "home": [about, team, admin],
        "about": [team],
        "team": [admin],
        "admin": [settings],
        "settings": [],
    }
    return site_map, adjacency


__all__ = ["build_default_site_map"]

