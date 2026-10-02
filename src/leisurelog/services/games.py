from leisurelog.domain.ports import GameCatalogStore


class GameImportService:
    def __init__(self, catalog: GameCatalogStore, processing):
        self.catalog, self.processing = catalog, processing

    def import_catalog(self, payload, games):
        changed = self.catalog.replace(payload, games)
        result = self.processing.rebuild() if changed else {}
        return {"changed": changed, **result, **self.catalog.status()}
