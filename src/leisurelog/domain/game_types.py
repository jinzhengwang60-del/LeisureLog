"""A declarative vocabulary, with one primary genre and separate descriptive tags.

The order is a deterministic suggestion policy, not a claim that a multi-genre
game has an objectively correct primary genre. User choices always win.
"""

import unicodedata

# Specific source genres precede broad genres. No game names are inferred here.
GAME_TYPES = (
    ("moba", "MOBA", ("moba", "multiplayer online battle arena")),
    ("arpg", "动作角色扮演", ("arpg", "action rpg", "动作角色扮演")),
    ("rts", "即时战略", ("rts", "real time strategy (rts)", "即时战略")),
    ("turn_strategy", "回合策略", ("turn-based strategy (tbs)", "回合策略")),
    ("card", "卡牌与桌游", ("card & board game", "card game", "卡牌", "卡牌与桌游")),
    ("visual_novel", "视觉小说", ("visual novel", "视觉小说")),
    ("fps", "第一人称射击", ("fps", "first-person shooter", "第一人称射击")),
    ("shooter", "射击", ("shooter", "射击")),
    ("fighting", "格斗", ("fighting", "格斗")),
    ("platform", "平台跳跃", ("platform", "platformer", "平台跳跃")),
    ("puzzle", "解谜", ("puzzle", "解谜")),
    ("racing", "竞速", ("racing", "竞速")),
    ("sports", "体育", ("sport", "sports", "体育")),
    ("music", "音乐与节奏", ("music", "rhythm", "音乐与节奏", "音游")),
    ("rpg", "角色扮演", ("rpg", "role-playing (rpg)", "role playing", "角色扮演")),
    ("strategy", "策略", ("strategy", "策略")),
    ("simulation", "模拟", ("simulator", "simulation", "模拟")),
    ("survival", "生存", ("survival", "生存")),
    ("sandbox", "沙盒", ("sandbox", "沙盒")),
    ("adventure", "冒险", ("adventure", "冒险")),
    ("action", "动作", ("action", "hack and slash/beat 'em up", "动作")),
    ("other", "其他游戏类型", ("其他游戏类型",)),
    ("unknown", "类型待补充", ()),
)
LABELS = {key: label for key, label, _ in GAME_TYPES}


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().casefold().split())


ALIASES = {
    normalized(alias): label for _, label, aliases in GAME_TYPES for alias in (*aliases, label)
}
ALIASES.update({"indie": "独立游戏", "open world": "开放世界", "open-world": "开放世界"})


def canonical_tags(tags) -> list[str]:
    result, seen = [], set()
    for tag in tags:
        name = ALIASES.get(normalized(tag), tag.strip())
        identity = normalized(name)
        if identity and identity not in seen:
            result.append(name)
            seen.add(identity)
    return result


def type_options() -> list[dict]:
    return [{"id": key, "label": label} for key, label, _ in GAME_TYPES]


def resolve_game_type(source_tags, override=None) -> dict:
    tags = canonical_tags(source_tags)
    automatic = next((key for key, label, _ in GAME_TYPES if label in tags), "unknown")
    primary = override["primary"] if override is not None else automatic
    return {
        "primary": primary,
        "label": LABELS[primary],
        "tags": canonical_tags(override["tags"]) if override is not None else tags,
        "source": "manual" if override is not None else "automatic",
        "automatic_primary": automatic,
        "automatic_label": LABELS[automatic],
        "automatic_tags": tags,
        "source_tags": list(source_tags),
    }


def validate_choice(primary, tags):
    if primary not in LABELS:
        raise ValueError("请选择支持的主类型")
    if not isinstance(tags, list) or len(tags) > 50:
        raise ValueError("补充标签最多 50 项")
    if any(not isinstance(t, str) or not t.strip() or len(t.strip()) > 80 for t in tags):
        raise ValueError("每个标签需为 1–80 个字符")
    return canonical_tags(tags)
