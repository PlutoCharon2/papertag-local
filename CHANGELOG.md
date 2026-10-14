# Changelog

## 0.7.10

- 启动时显示 Windows 托盘图标，关闭窗口后隐藏到托盘，后台任务继续运行。
- 托盘双击或“打开文献库”恢复窗口，“退出软件”完全退出；系统关机正常放行。
- 再次启动同一文献库时唤回已有窗口，不启动重复分析队列。

## 0.7.9

- 新增浅色青蓝主题，统一导航、按钮、标签、列表与弹窗的视觉层级。
- 文献状态独立着色，年份与期刊保持次要文字样式；选中项和筛选项更清晰。
- 保留 PDF 阅读面积、固定导航、标签管理与数据保存行为。

## 0.7.8

- 导入与导出、标签体系、使用说明页面滚动时固定顶部导航。
- 修改已有标签紧接添加正式标签，阅读建议移至管理列表之后。
- 压缩添加标签表单和管理行的纵向间距；保留文献库数量栏固定行为。

## 0.7.7

- 中文名称改为垃圾桶；统一按钮、颜色和标签管理页样式。
- 筛选标签后文献列表回到顶部，列表标题固定并压缩至36px。
- 标签名称使用桌面可用的编辑窗口；增加搜索、已删除查看与管理入口。
- 删除标签保留论文、其他归属及历史记录，可恢复。

## 0.7.6

- 压缩导航、搜索、文献信息区域，扩大PDF阅读区域。
- 新增专注阅读，一键隐藏两侧栏及顶部导航，Escape可退出。
- 隐藏顶部服务状态、待标签/历史版本选项，导出移到导入与导出页。

## 0.7.5

- 内嵌 Mozilla PDF.js，直接读取原始PDF，替代PNG预览；支持文本选择、搜索、连续阅读和矢量内容重新缩放。
- 扫描PDF保留原扫描内容，不伪装为矢量文档。

## 0.7.4

- PDF 连续滚动，按需加载页面，移除内层滚动条及详情辅助内容。
- 重新分析与标签、证据按钮同行。
- 已有文件名年份和刊名简称直接显示；后续打标签一并提取刊名、简称与文献类型，不增加独立API调用。

## 0.7.3

- 左侧文献卡片在年份后显示期刊，手动编辑后同步刷新。

## 0.7.2

- 点击文献直接显示原始PDF页面，支持翻页、缩放和证据页码跳转。
- 标签审核与证据结果移至按钮打开的窗口，摘要默认收起。
- 新增期刊/会议字段和本地手动编辑，兼容既有分析。

## 0.7.1

- 超过30页仅定位并分析目录，保留真实PDF页序；无完整目录时停止。
- 目录级结果明确标注，禁止正文断言及结果维度标签。
- 保留已有本地结果，不自动重跑已完成任务。

## 0.7.0 (experimental prerelease)

Initial public release: local PDF imports and immutable archives, incremental content-hash updates, domestic vision API profiles with DPAPI key storage, dynamic tags, manual decisions, queue pause/resume, offline revalidation, partial result reporting and per-stage timing.

Removed machine-specific default literature folders and excluded all private runtime / validation material from public artifacts. Existing locally registered folders remain in the user's database. Research output accuracy is not guaranteed.
