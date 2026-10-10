# 界面素材说明

2026-10-10 新增三套独立皮肤。素材全部放在本地静态目录并随安装包分发，不引用远程图片、字体或图片生成服务。

## 窗边（原晴空动漫）

- 文件：`src/leisurelog/api/static/sunny-afternoon.png`
- 使用内置 image_gen 工具生成，未使用 API/CLI 后备方式。
- 原创角色与窗边午后场景，用于页头和风格面板缩略图；人物位于右侧，左侧留给实际页面文字。
- 原图未经二次图像编辑，页面仅以 CSS 调整显示比例和叠加浅色/深色渐变。
- 2026-10-10 起插画跟随真实时间变化：`sky-clock.js` 按 11 个时刻的关键帧插值出当前配色，`skins/sunny.css` 在插画图层上用 `background-blend-mode` 叠加正片叠底色调（决定时段）与滤色光层（地平线霞光、斜阳、月亮、台灯暖光和游戏机屏幕微光）。光层坐标按插画比例 2:1 定位，换图时需要一起调整。

最终生成提示词：

```text
Use case: illustration-story. Asset type: original landscape hero illustration for a local leisure activity dashboard called LeisureLog, anime summer theme. Create a polished wide 2:1 landscape anime illustration, crisp delicate linework and soft cel shading. Scene: a sunny quiet afternoon by a large open window, clear azure sky, fluffy white clouds, leafy tree outside, cream curtains and a pale wood desk. On the right third, an original young adult woman wearing casual pale blue clothing and headphones, resting near the window with a handheld game console. Relaxed contemplative mood, tasteful mature anime character design, no existing franchise resemblance. Composition: right-weighted subject and detailed scenery; left half calm pale sky and very light cream wall with ample clean negative space, suitable for readable UI placed above it. Palette sky blue, warm ivory, muted coral, green accents, airy luminous daylight. Professional anime background art, refined and cohesive, beautiful environmental detail. This is an illustration asset, not a website screenshot: no UI, no cards, no text, no typography, no logos, no watermark.
```

## 周刊（原纸本杂志）

使用本地 CSS 制作刊头、细线、分栏和轻微纸张纹理。中文衬线字体优先选择系统已有字体，以宋体作后备；不额外下载字体。

## 掌机（原像素街机）

- 文件：`src/leisurelog/api/static/arcade-world.svg`
- 原创代码绘制的矢量像素图。2026-10-10 重画为 PICO-8 十六色调色板的夜景：星星、月亮、山丘、亮灯的小镇、屋顶上的猫和三颗生命值爱心。
- 使用 crispEdges 保留硬边，配合 CSS 按键、侧栏和数据面板。像素装饰中的爱心不是活动奖励或虚构统计数据。
