# PaperTag Local · 垃圾桶

Windows 11 本地 AI 文献标签库。导入 PDF 或文件夹，使用你配置的视觉模型 API 生成标签、摘要及带页码的断言，本地保存结果并增量更新。

**当前为实验性预发布版。** AI 输出和页码通过格式校验不代表科研判断正确；关键结论需要人工核对原文。部分结果明确标为待补充，不冒充完整成功。

## 安装

从本仓库 Releases 下载 `PaperTagLocal-Setup-0.7.10.exe`，选择安装目录。Windows 11 x64，需 Microsoft Edge WebView2。安装包未签名，系统可能要求你确认来源。

安装包不包含 API 密钥、账号会话、论文、个人目录、数据库、历史分析或日志。第一次使用没有预设文献目录；请自行选择 PDF / 文件夹和配置 API。升级会复用本机已有数据库，这是本地数据复用，不是安装包携带了私人配置。

## 本版更新

- 内嵌 PDF.js 原始 PDF 阅读器：连续滚动、文本选择、搜索和专注阅读。
- 浅色青蓝界面，标签管理支持搜索、重命名、删除和恢复；删除标签保留论文和其他归属。
- 文献卡片显示年份及期刊 / 会议简称；后续 AI 分析一并提取基础书目信息。
- 超过 30 页的文献仅分析目录；找不到完整目录时停止，不生成正文结论。
- 启动后显示托盘图标，点关闭按钮隐藏窗口，后台任务继续；双击托盘或再次启动可恢复窗口。

**升级前请完全退出旧程序。** 已支持托盘的版本需右键托盘图标选择“退出软件”，然后安装到原目录。已有文献、分析、人工决定和 API 配置继续复用。Windows 可能将托盘图标放入右下角隐藏图标区。隐藏窗口仍占用内存。

## 使用

1. 点击「API 配置」，选择千问百炼、豆包火山方舟、DeepSeek 或智谱。
2. 填写自己账号的密钥和支持图片的模型 ID，保存后可测试小图片识别（产生少量 API 费用）。
3. 导入 PDF 或文件夹。新增 / 修改内容自动排队；已有结果复用。
4. 左侧筛选随实际标签变化。人工拒绝和停用标签优先。
5. 需要停止时点击「全部暂停」。失败结果可在暂停后本地重校验，不调用模型；缺失信息不会被补造。

默认千问视觉模型 `qwen3.7-flash`；豆包填写已开通的视觉模型 / 接入点 ID；DeepSeek 预设 `deepseek-flash`；智谱预设 `glm-4.6v-flash`。模型可用性和计费以服务商为准。

## 隐私与数据

- 数据库和 PDF 归档保存在本机用户目录中，与安装目录分开；卸载不主动删除文献数据。
- API 密钥由当前 Windows 用户的 DPAPI 加密，不回显；更换用户或电脑后重新配置。
- 执行分析时，所选 PDF 页面图像和所需提示词会发送给你选择的服务商。这不是离线 AI 模型。
- 密钥仅发送到选定服务商的官方 HTTPS 接口，拒绝跨域重定向。没有遥测上传、自动 GitHub 上传或云端同步功能。
- 任务回执、AI 原始返回和日志留在本地。分享导出的文件或报错前请自行检查其中的文献内容及路径。

## 开发与构建

Python 3.12、FastAPI、SQLite、PyMuPDF、pywebview、PyInstaller、Inno Setup 6。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q --basetemp tmp/pytest
.\build-desktop.ps1
# 安装 Inno Setup 后执行：
ISCC.exe installer.iss
```

运行源码桌面版：`.\.venv\Scripts\pythonw.exe desktop.py`。网页调试版：`start.ps1`。测试使用虚拟密钥和模拟接口，不消耗真实 API 额度。

## 许可证

AGPL-3.0-only，见 [LICENSE](LICENSE)。PDF 组件 PyMuPDF / MuPDF 使用 AGPL / 商业双许可；本项目使用其开源许可。第三方组件保留各自许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 `licenses/`。

## English

A local-first Windows PDF research library with remote vision API tagging, persistent results, dynamic facets, manual decisions and content-hash incremental updates. Bring your own API key. PDF page images are sent to the selected provider; the app is not an offline AI model. Experimental prerelease: review research claims against the original paper.

超过30页的文献仅做目录级分析：先用前30页的缩略图让AI定位目录，再上传目录页生成覆盖主题标签。未找到完整目录时停止；不生成正文结论。目录定位和目录分析可能各产生一次API调用，已保存结果继续复用。
