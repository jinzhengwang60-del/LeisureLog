"""Suggested categories for unclassified apps. Only a suggestion: nothing is saved until the
person confirms it on the 待分类 page, where it becomes an ordinary app-wide rule."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Suggestion:
    category: str
    content: str | None
    reason: str


def _table(category: str, reason: str, entries: dict[str, str | None]) -> dict:
    return {
        app.casefold(): Suggestion(category, content, reason) for app, content in entries.items()
    }


KNOWN: dict[str, Suggestion] = {
    **_table("game", "游戏本体", {
        "eldenring.exe": "艾尔登法环",
        "Cyberpunk2077.exe": "赛博朋克 2077",
        "DaveTheDiver.exe": "潜水员戴夫",
        "SB-Win64-Shipping.exe": "剑星",
        "YF.exe": "Your Fiancée",
        "Client-Win64-Shipping.exe": "鸣潮",
        "GenshinImpact.exe": "原神",
        "ZenlessZoneZero.exe": "绝区零",
        "StarRail.exe": "崩坏：星穹铁道",
        "League of Legends.exe": "英雄联盟",
        "javaw.exe": "我的世界",
    }),
    **_table("game", "游戏启动器或辅助工具", {
        "launcher_main.exe": "鸣潮",
        "KRSDKExternal.exe": "鸣潮",
        "KRWebClient.exe": "鸣潮",
        "KRNotifyWnd.exe": "鸣潮",
        "ok-ww.exe": "鸣潮",
        "XXMI Launcher.exe": "鸣潮",
        "Wuwa Mod Fixer v3.6.0.exe": "鸣潮",
        "BetterGI.exe": "原神",
        "HYP.exe": "米哈游启动器",
        "REDlauncher.exe": "赛博朋克 2077",
        "YourFiancéeModTool.exe": "Your Fiancée",
        "Browndust2Starter.exe": "棕色尘埃 2",
        "LeagueAkari.exe": "英雄联盟",
        "LeagueClientUx.exe": "英雄联盟",
        "Plain Craft Launcher 2.exe": "我的世界",
        "wegame.exe": "WeGame",
        "browser.exe": "WeGame",
        "TapTap.exe": "TapTap",
        "steam.exe": "Steam",
        "steamwebhelper.exe": "Steam",
        "EpicGamesLauncher.exe": "Epic Games",
        "Playnite.DesktopApp.exe": "Playnite",
        "ZFGameBrowser.exe": None,
    }),
    **_table("music", "音乐软件", {
        "cloudmusic.exe": "网易云音乐",
        "QQMusic.exe": "QQ 音乐",
        "kugou.exe": "酷狗音乐",
        "Spotify.exe": "Spotify",
    }),
    **_table("anime", "看番软件", {"kazumi.exe": "Kazumi"}),
    **_table("video", "视频软件", {
        "PotPlayerMini64.exe": "PotPlayer",
        "vlc.exe": "VLC",
        "bilibili.exe": "哔哩哔哩",
    }),
    **_table("social", "聊天软件", {
        "WeChatAppEx.exe": "微信",
        "Weixin.exe": "微信",
        "TTVoice.exe": "TT 语音",
        "Discord.exe": "Discord",
        "QQ.exe": "QQ",
    }),
    **_table("work", "办公、学习或开发工具", {
        "wps.exe": None,
        "photolaunch.exe": None,
        "QQEX.exe": None,
        "Notepad.exe": None,
        "Notion.exe": None,
        "Code.exe": None,
        "WINWORD.EXE": None,
        "EXCEL.EXE": None,
        "POWERPNT.EXE": None,
        "JianyingPro.exe": "剪映",
    }),
    **_table("system", "系统组件、网络或安全工具", {
        "clash-verge.exe": None,
        "uu.exe": None,
        "uu_ball.exe": None,
        "sysclean.exe": None,
        "HipsLog.exe": None,
        "HipsMain.exe": None,
        "NVIDIA App.exe": None,
        "nvcplui.exe": None,
        "dwm.exe": None,
        "PickerHost.exe": None,
        "CredentialUIBroker.exe": None,
        "WerFault.exe": None,
        "FileDialogWorker.exe": None,
        "AppInstaller.exe": None,
        "msiexec.exe": None,
        "NIUpdateService.exe": None,
        "ACE-Helper.exe": None,
        "SafeMail.exe": None,
        "QQScreenshot.exe": None,
        "AweSun.exe": None,
        "Bandizip.exe": None,
        "quark.exe": None,
        "BaiduNetdisk.exe": None,
        "BaiduNetdiskUnite.exe": None,
        "OKX-Security-Assistant-Core.exe": None,
        "explorer.exe": None,
        "LockApp.exe": None,
        "ApplicationFrameHost.exe": None,
        "SearchHost.exe": None,
        "ShellExperienceHost.exe": None,
        "StartMenuExperienceHost.exe": None,
        "SystemSettings.exe": None,
        "Taskmgr.exe": None,
        "wallpaper32.exe": None,
        "wallpaper64.exe": None,
        "wallpaperui.exe": None,
    }),
}

INSTALLER = re.compile(r"(setup|install|uninst|unins|update|updater|卸载|安装)", re.IGNORECASE)
PACKED_TITLES = ("输入密码", "浏览文件夹", "选择解压路径")


def suggest(app: str, sample_titles: list[str] | None = None) -> Suggestion | None:
    """Best guess for an app, or None when there is nothing sensible to say."""
    name = (app or "").strip()
    if not name or name.casefold() == "unknown":
        return None
    known = KNOWN.get(name.casefold())
    if known is not None:
        return known
    lowered = name.casefold()
    titles = sample_titles or []
    if lowered.endswith(".tmp") or INSTALLER.search(name):
        return Suggestion("system", None, "安装、更新或卸载程序")
    if lowered.endswith("-win64-shipping.exe"):
        return Suggestion("game", None, "虚幻引擎游戏的常见进程名")
    if titles and all(INSTALLER.search(t) for t in titles):
        return Suggestion("system", None, "安装、更新或卸载程序")
    # Self-extracting archives (mod packs etc.) ask for a password or a folder and then exit.
    packed = all(any(k in t for k in PACKED_TITLES) or "BiliBili" in t for t in titles)
    if not name.isascii() and titles and packed:
        return Suggestion("system", None, "自解压的压缩包")
    if "launcher" in lowered:
        return Suggestion("game", None, "名字里带 Launcher，多半是游戏启动器")
    return None
