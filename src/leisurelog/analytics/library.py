from leisurelog.domain.ports import LibraryStore


def catalog(store: LibraryStore, query: str, category: str, sort: str, limit: int, offset: int):
    return store.listing(query.strip(), category, sort, limit, offset)


def content_detail(store: LibraryStore, item_id: str, limit: int, offset: int):
    return store.detail(item_id, limit, offset)
