# EXE 打包实施记录

- 状态：**已完成并验收**
- 日期：2026-08-27
- 依赖：[08-V2打磨方案二](08-V2打磨方案二.md)
- 产物：`for_exe/申论素材助手/`（约 570MB，免安装）

## 一、产物结构

```
for_exe/申论素材助手/
├── 申论素材助手.exe    程序主文件（双击运行，GUI 无控制台）
├── _internal/          依赖库 + seed 种子 + app/static 前端
│   ├── seed/           （phrases/topic_cards/expressions/topics/cases）
│   └── app/static/     （index.html/app.js/style.css）
├── sucai/              范文库（13 个 docx，可写，用户可增删）
├── data/               首次运行自动生成（种子初始化，不含 API Key）
└── 说明.txt            使用说明
```

## 二、构建方法

```bash
cd for_exe
python -m PyInstaller 申论素材助手.spec --noconfirm --distpath . --workpath build
# 然后复制 sucai/ 与 说明.txt 到产物目录
```

spec 关键点：
- `console=False`（GUI 程序）
- datas 收集 seed 5 个文件 + app/static
- hiddenimports 补 uvicorn 子模块（循环/协议/生命周期）
- upx=False（避免杀软误报）

## 三、打包中解决的坑

1. **uvicorn windowed 崩溃**：`console=False` 下 uvicorn 自带日志配置（dictConfig）因 stdout 为 None 的 `isatty()` 崩溃。修复：`uvicorn.Config(log_config=None)` 禁用其日志配置 + `_setup_logging` 仅在 stdout 存在时加 StreamHandler。
2. **种子路径**：打包后种子在 `sys._MEIPASS/seed`（onedir 即 `_internal/seed`），而数据目录应在 exe 旁。新增 `store.project_root()/seed_dir()/sucai_dir()` 共享函数统一解析（开发/打包双兼容），main/pipeline/server 三处统一改用。
3. **spec 无 `__file__`**：PyInstaller 执行 spec 时无 `__file__`，改用 `SPECPATH` 定位。
4. **验证脚本读旧端口**：app.log 是追加日志，需先清空再启动，避免读到历史端口。

## 四、验收结果（实机验证）

| 检查项 | 结果 |
|---|---|
| exe 启动（无 Python 环境依赖） | ✅ 服务就绪 |
| 健康检查 / 前端页面 | ✅ 200 + 页面渲染 |
| 种子数据初始化（语段 56/表达 40） | ✅ data/ 自动生成 |
| sucai 13 个 docx 可见 | ✅ 文件列表正确 |
| 内嵌浏览器加载 | ✅（前端页面通过） |

## 五、分发注意

- 免安装：整个 `申论素材助手/` 文件夹拷走即可用（需完整复制，不能只拷 exe）
- **不带用户 API Key**（仅种子内容），接收方需自行填 key
- 杀软可能误报 PyInstaller 产物，说明.txt 已注明
- 打包版 ≈ 570MB（PySide6+QtWebEngine 体积代价，用户已接受）
