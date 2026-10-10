from leisurelog.domain.library import ContentIdentity
from leisurelog.domain.ports import LibraryStore


class LibraryService:
    def __init__(self, store: LibraryStore):
        self.store = store

    def merge_many(self, groups: list[tuple[str, list[str]]]) -> int:
        """Merge several groups at once; every merge is checked like a single one."""
        merged = 0
        for target_id, source_ids in groups:
            for source_id in source_ids:
                self.merge(target_id, source_id)
                merged += 1
        return merged

    def rename(self, item_id: str, name: str, notes: str):
        self.store.item(item_id)
        self.store.update_item(item_id, name.strip(), notes.strip())

    def add_alias(self, item_id: str, app: str, name: str):
        item = self.store.item(item_id)
        self.store.add_alias(item_id, ContentIdentity(app.strip(), item["category"], name.strip()))

    def merge(self, target_id: str, source_id: str):
        if target_id == source_id:
            raise ValueError("不能合并到自身")
        source, target = self.store.item(source_id), self.store.item(target_id)
        if source["category"] != target["category"]:
            raise ValueError("只能合并同一分类的内容；分类错误请先在活动记录中纠正")
        self.store.merge(source_id, target_id)

    def split(self, item_id: str, alias_id: str) -> str:
        self.store.item(item_id)
        alias = self.store.alias(alias_id)
        if alias["item_id"] != item_id:
            raise ValueError("这个名称已经不属于当前条目，请刷新")
        return self.store.split(alias_id)
