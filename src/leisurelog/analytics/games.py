from leisurelog.domain.ports import GameStatisticsStore


def game_listing(store: GameStatisticsStore, query, scope, sort, limit, offset):
    return store.listing(query.strip(), scope, sort, limit, offset)


def game_detail(store: GameStatisticsStore, key, limit, offset):
    return store.detail(key, limit, offset)
