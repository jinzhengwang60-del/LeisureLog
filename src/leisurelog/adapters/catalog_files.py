"""Read only the two paths configured by the host, with bounded file sizes."""

from pathlib import Path

from leisurelog.domain.game_catalog import GameCatalogFiles, GameCatalogUnavailable


class LocalGameCatalogFiles:
    def __init__(self, export_path: Path, bindings_path: Path):
        self._export, self._bindings = export_path, bindings_path

    @staticmethod
    def _read(path, limit, encoding):
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise GameCatalogUnavailable("游戏资料文件超过大小限制")
        return data.decode(encoding)

    def read(self):
        try:
            return GameCatalogFiles(
                self._read(self._export, 10_000_000, "utf-8-sig"),
                self._read(self._bindings, 1_000_000, "utf-8"),
            )
        except (OSError, UnicodeError, ValueError) as error:
            raise GameCatalogUnavailable("游戏资料文件缺失或无法读取") from error
