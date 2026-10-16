from leisurelog.domain.game_catalog import GameCatalogImport
from leisurelog.domain.ports import GameCatalogStore


class GameImportService:
    def __init__(self, catalog: GameCatalogStore, processing):
        self.catalog, self.processing = catalog, processing

    def import_catalog(self, proposal: GameCatalogImport):
        if type(proposal) is not GameCatalogImport:
            raise TypeError("游戏资料导入需要经过验证的提案")
        changed = self.catalog.replace(proposal.payload(), list(proposal.games))
        result = self.processing().rebuild() if changed else {}
        return {"changed": changed, **result, **self.catalog.status()}
