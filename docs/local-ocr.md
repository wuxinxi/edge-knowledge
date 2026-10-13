# 本地 OCR 与平台支持

图片语义检索使用 EmbeddingGemma 2；可复制的图片文字来自独立 OCR。两者都在本机处理。

| 平台    | 默认文字识别                         | 本地替代                   |
| ------- | ------------------------------------ | -------------------------- |
| macOS   | Apple Vision（中文/英文）            | RapidOCR / ONNX Runtime    |
| Windows | RapidOCR / ONNX Runtime（中文/英文） | 依赖不可用则明确显示不可用 |
| Linux   | RapidOCR / ONNX Runtime（中文/英文） | 依赖不可用则明确显示不可用 |

开发环境安装：

```sh
uv sync --project backend --extra embedding --extra ocr --group dev
```

ocr extra 安装跨平台 RapidOCR 及其 ONNX Runtime/OpenCV 依赖；仅 macOS 安装 Apple Vision 的 Python 桥接。固定使用 `rapidocr-onnxruntime==1.4.4`，其 wheel 内含检测、方向、识别模型和字典，避免首次识别时联网下载。这里没有改为新版 rapidocr 的默认自动下载行为。依赖安装本身需联网；安装完成后图片识别不联网，不调用 DeepSeek。

设置的运行状态显示当前优先引擎，独立图片识字弹窗显示本次实际引擎。macOS 文字识别返回空表示图片未检测到文字，不重复运行替代引擎；系统识别报错/不可用时才尝试可用的跨平台引擎。OCR 结果保留原始识别文字、置信度和归一化区域；图表坐标/标签不自动重构为表格。图片文字的顺序与准确率仍需真实语料评估。

验证：`backend/tests/test_portable_ocr.py` 在本机实际运行 ONNX 模型，阻止网络连接后识别自制图片，检查文本与区域；另覆盖 Windows 平台选择、缺模型、系统识别失败、空白图片、非法内容。Windows 后端程序路径有专门测试。真实 Windows/Linux 的运行库、权限、凭据库与安装包尚需目标机器验收，不把在 macOS 上调用跨平台模型的测试冒称为 Windows 实机测试。

已有 macOS 图片 OCR 内容可以通过备份恢复到其他平台，读取历史内容不依赖 Apple Vision。历史导入时 OCR 不可用的图片不会被本次修改自动补识别；OCR 引擎可用后需要独立识别，若需要让补识别文字进入索引，应重新导入对应图片（存在重复索引时先移入回收站再导入）。已有缺 OCR 的索引不会静默修改。

参考：[RapidOCR 1.4.4 发布包](https://pypi.org/project/rapidocr-onnxruntime/1.4.4/)、[RapidOCR 官方文档](https://rapidai.github.io/RapidOCRDocs/)。
