"""Serve only host-selected roots and active, explicitly declared resources."""

import mimetypes
from pathlib import Path

from leisurelog.domain.plugin_extensions import resource_name


class PluginResources:
    def __init__(self, roots):
        self.roots = {owner: Path(root).resolve() for owner, root in roots.items()}

    def path(self, owner, asset):
        resource_name(asset)
        root = self.roots[owner]
        path = (root / asset).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise KeyError(asset)
        return path

    def validate(self, owner, pages):
        for asset in {asset for page in pages for asset in page.assets}:
            if self.path(owner, asset).stat().st_size > 2 * 1024 * 1024:
                raise ValueError("页面资源超过 2 MiB")


class PluginPageHost:
    def __init__(self, extensions, roots, aliases=()):
        self._extensions = extensions
        self._resources = roots if type(roots) is PluginResources else PluginResources(roots)
        self._roots = self._resources.roots
        self._aliases = {(value.owner, value.name): value.path for value in aliases}

    def navigation(self):
        return {
            "managed_urls": sorted(set(self._aliases.values())),
            "pages": [
                {
                    "plugin_id": owner,
                    "name": page.name,
                    "title": page.title,
                    "url": self._aliases.get(
                        (owner, page.name), f"/plugins/{owner}/pages/{page.name}"
                    ),
                }
                for owner, _, page in self._extensions.pages()
                if owner in self._roots
            ],
        }

    def read(self, owner, *, name=None, asset=None):
        if owner not in self._roots:
            raise KeyError(owner)
        ticket, page = self._extensions.page(owner, name, asset=asset)
        asset = page.document if name is not None else asset
        path = self._resources.path(owner, asset)
        # Bounded reads; a file changing during the read cannot bypass the byte limit.
        with path.open("rb") as source:
            value = source.read(2 * 1024 * 1024 + 1)
        if len(value) > 2 * 1024 * 1024:
            raise ValueError("页面资源超过 2 MiB")
        self._extensions.check_page(ticket)
        return value, mimetypes.guess_type(asset)[0] or "application/octet-stream"
