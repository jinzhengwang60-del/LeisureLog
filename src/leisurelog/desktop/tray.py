"""Optional Windows tray; all recording stays in the application worker."""

import os
from threading import Thread


def start_tray(runtime, open_page):
    from PIL import Image, ImageDraw
    from pystray import Icon, Menu, MenuItem

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 60, 60), fill="#498578")
    draw.arc((14, 14, 50, 50), 5, 350, fill="white", width=3)
    draw.line((32, 19, 32, 32, 43, 38), fill="white", width=3)

    def toggle(icon, item):
        if not runtime.preferences.setup_completed:
            open_page()
        else:
            runtime.update_sync(not runtime.preferences.sync_enabled)
        icon.update_menu()

    icon = Icon(
        "LeisureLog",
        image,
        "LeisureLog · 本机活动记录",
        Menu(
            MenuItem("打开活动记录", lambda icon, item: open_page(), default=True),
            MenuItem("本机设置与接入", lambda icon, item: open_page("/setup")),
            MenuItem(
                lambda item: "停止自动同步" if runtime.preferences.sync_enabled else "开启自动同步",
                toggle,
            ),
            MenuItem("打开个人数据目录", lambda icon, item: os.startfile(str(runtime.paths.root))),
            Menu.SEPARATOR,
            MenuItem("退出 LeisureLog", lambda icon, item: runtime.shutdown()),
        ),
    )
    thread = Thread(target=icon.run, name="leisurelog-tray", daemon=True)
    thread.start()
    return icon
