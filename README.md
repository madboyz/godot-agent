# Godot Knowledge

本地 Godot 知识库、SQLite FTS5 查询核心、stdio MCP 服务和 Agent Skill。
Python 3.12+，面向 Windows、Linux 和 macOS，无外部 AI API 或密钥依赖。

## 安装与使用

在任意位置取得源码后，安装为独立工具，再安装随包分发的 Skill 和 MCP 接入：

```sh
uv tool install .
godot-knowledge install
```

也可在自己的 Python 环境中使用 `python -m pip install .`。命令没有加入 PATH 时，
用该环境的 `python -m godot_knowledge.cli` 调用。安装后的 wheel 包包含 Skill，
运行与安装 Skill 都不需要保留源码目录。

安装器只更新 `mcp_servers.godot-knowledge` 的启动命令、参数和超时，
保留其他配置，并在首次修改前保存配置备份。同步工具超时设为 900 秒。
默认使用 `CODEX_HOME`，未设置时使用 `~/.codex`；
可通过 `install --codex-home PATH` 指定其他 Codex 用户目录。
启动解释器由当前安装环境发现，接入配置中的路径在各设备安装时生成，
不携带开发者的目录、用户名或虚拟环境布局。

在新聊天中调用 `$godot-knowledge`，或直接使用 CLI：

```sh
godot-knowledge status
godot-knowledge query get_api --json '{"class_name":"Node","member":"_ready"}'
godot-knowledge query search --json '{"query":"线程安全"}'
godot-knowledge query get_topic --json '{"topic":"渲染"}'
```

## 数据目录

CLI 与 MCP 使用同一套目录解析规则，优先级为：

1. 命令行 `--data PATH` 或 MCP 创建时的显式路径。
2. 环境变量 `GODOT_KNOWLEDGE_DATA`。
3. 系统用户数据目录，由 `platformdirs` 解析。

| 系统 | 默认位置 |
| --- | --- |
| Windows | `%LOCALAPPDATA%/godot-knowledge` |
| Linux | `$XDG_DATA_HOME/godot-knowledge`，未设置时为 `~/.local/share/godot-knowledge` |
| macOS | `~/Library/Application Support/godot-knowledge` |

默认值不依赖源码目录、包安装目录或当前工作目录。例如为当前设备选择一个资料目录：

```sh
godot-knowledge --data ./knowledge-data install
godot-knowledge --data ./knowledge-data status
```

安装器会将选定的数据目录写入当前设备的 MCP 配置，之后从其他工作目录启动 MCP
仍使用这份资料。CLI 若要使用相同的非默认目录，应继续传入 `--data` 或设置环境变量。
旧版使用源码目录的 `data/`；升级时用 `--data ./data install` 可继续使用已有资料。

## 数据和更新

首次同步匹配本机引擎的源码、文档并选择基线：

```sh
godot-knowledge sync --allow-partial --select
```

引擎发现顺序：`--engine` / MCP 的 `engine_executable` 参数、
`GODOT_EXECUTABLE` 环境变量、PATH 上的 `godot` 和 `godot4`。
参数可接受可执行文件、PATH 命令名或 macOS `.app` 包。
没有找到引擎时会说明如何配置，不猜测用户安装位置。

```sh
godot-knowledge sync --engine godot4 --select
```

去掉 `--allow-partial` 后，上游同步任一失败都会拒绝发布。使用 `--offline`
只采集本机 API；覆盖缺口始终可见。`--select` 是显式选择默认基线的 CLI 选项，
MCP 的 `sync_sources` 只发布候选，之后调用 `select_snapshot` 切换。

源代码 ref 必须是与可执行文件匹配的官方版本标签或 commit；校验最终 commit
与引擎自报 hash 前缀一致。手册使用匹配的 `major.minor` 分支，记录固定 commit，
并标记 `minor_branch`，不声称它与补丁发布时刻完全一致。
同步优先下载官方 GitHub 源码归档，从 Git PAX 元数据记录实际 commit；归档不可用时
回退到浅层 Git 获取。归档会校验路径、大小和提交信息，支持 Windows 长路径。

```sh
godot-knowledge query compare_snapshots --json '{"before":"SNAPSHOT_A","after":"SNAPSHOT_B"}'
godot-knowledge query select_snapshot --json '{"snapshot":"SNAPSHOT_B"}'
```

选定的数据目录包含：

- `snapshots/<id>/sources/`：引擎导出的 JSON/XML 和下载的官方仓库。
- `snapshots/<id>/index.sqlite`：该版本独立的只读查询索引。
- `snapshots/<id>/manifest.json`：版本、提交、采集时间、文件哈希、覆盖缺口。
- `active.json`：原子写入的默认快照指针。
- `staging/`：未发布候选，失败原因写入 `failure.json`。

更新先完整构建并校验候选，再原子发布。查询固定一次解析出的快照；
默认指针发生变化也不会让一次调用混入其他版本。失败或离线不影响已发布资料。
同步进程由数据目录中的 `sync.lock` 互斥；如果进程被强制杀死，先确认不存在正在运行的同步，
再移除残留锁并重试。失败候选保留供诊断，不自动删除原始资料。

查询核心升级后，可以使用已缓存的固定资料离线构建新索引，不修改旧快照：

```sh
godot-knowledge reindex --snapshot SNAPSHOT_ID --select
```

迁移时复制整个数据目录，并在新设备上用 `--data` 或环境变量指定它。
索引与原文之间使用快照内的相对路径；历史 manifest 中的引擎位置只用于溯源，
查询不会要求旧设备上的可执行文件存在。源码仓库和虚拟环境不需要一起复制。

## 工具

| MCP 工具 | 用途 |
| --- | --- |
| `status` | 基线、来源、覆盖缺口和索引计数 |
| `search` | 中英文关键词、主题与资料类型过滤 |
| `get_api` | 类、成员、继承、重载、参数、信号、枚举常量和状态 |
| `get_topic` | 官方手册片段及相关 API |
| `read_source` | 按来源 ID 或快照相对路径读取限定范围的原文与代码 |
| `sync_sources` | 导出本机资料，同步固定版本，构建候选 |
| `compare_snapshots` | API 语义变化和文档文件变化 |
| `select_snapshot` | 显式切换默认基线 |

查询返回快照、版本、来源路径和行号；JSON 补充类型使用类名定位。
中文检索依靠主题别名，不是任意自然语言语义搜索。API XML 为主，
JSON 补充绑定类型和内置说明，保留官方原文。`source` 定位签名，
`description_source` 存在时单独定位说明出处，`read_source` 按 ID 优先读取说明。
`availability=source_only` 表示只有源码参考，不能据此认定本机已编译该类。
默认每次返回有限条目，可通过 `next_offset`
继续读取 API；原文读取最多 200 行或 16,000 字符。

`get_topic` 提供需要进一步阅读的证据，不自动生成已验证的引擎限制结论。
缺少证据标记 `unconfirmed`。第一版不做 C++ 调用图、编辑器远程控制、
引擎 fork、GitHub 推送或定时更新。

## 验证

从源码开发：

```sh
uv sync --extra dev
uv run godot-knowledge install
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv build
uv run python scripts/verify_package.py
```

`scripts/install.ps1` 是可选的 PowerShell 便捷入口，内部调用同一个 Python 安装命令。
包安装验证会在源码目录外的新环境中安装 wheel、查询并安装 Skill，检查分发内容。
CI 配置覆盖 Windows、Linux、macOS；实际执行状态以 CI 运行结果为准。

测试覆盖继承和覆盖、重载、默认参数、信号、枚举、状态标记、中英文检索、
来源范围、版本隔离、并发切换、断网、提交不匹配、更新中断，以及官方 MCP SDK
客户端通过真实 stdio 子进程调用工具。实际引擎同步及验收记录见
`docs/validation.md`。

本项目代码与下载的上游资料分别管理；上游内容保留原仓库中的许可文件。
