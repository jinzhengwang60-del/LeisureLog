// Shared display names. Keep stored category IDs and custom categories unchanged.
export const categoryLabels = Object.freeze(Object.assign(Object.create(null), {
  unknown: "未分类", game: "游戏", video: "视频", film: "影视", anime: "动漫",
  reading: "阅读", music: "音乐", social: "社交", live: "直播", browsing: "网络闲逛",
  work: "工作", study: "学习", create: "创作", coding: "编程", office: "文档与办公",
  design: "设计与制作", meeting: "会议", system: "系统与工具", other: "其他",
}));

export function categoryName(value) {
  // A legacy library alias is display-only, not another correction choice.
  return categoryLabels[value === "movie" ? "film" : value] || value;
}
