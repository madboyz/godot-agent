# 第一版验收记录

验收日期：2026-10-31，Windows / Python 3.12.14 / 官方 MCP Python SDK 1.30.0。

## 当前资料

- 默认快照：`reindex-20261031T061913-fc9f6f38`。
- 本机引擎：`4.7.1.stable.official.a13da4feb`。
- 引擎源码提交：`a13da4feb8d8aefc283c3763d33a2f170a18d541`，
  与可执行文件自报 hash 一致。
- 手册：`godot-docs` 的 `4.7` 分支，
  提交 `9adca4c1c72917bfe1b7be3108abed5ce26696a6`。
- 源码为精确引擎提交；手册为固定提交的小版本分支资料。
- 31,383 条索引记录：1,079 类、10,732 方法、6,999 属性、
  6,012 常量、154 构造函数、351 运算符、503 信号、
  635 主题项、36 注解、4,882 手册片段。
- 本机 API、匹配源码和手册均已取得，来源覆盖缺口为空。
- 部分源码类不属于本机导出 API，使用 `source_only` 明确标记。

本机 `--doctool` 导出的 XML 含签名但说明为空，因此索引保留导出签名，
从匹配源码 XML 合并说明；离线时也可从带文档的 JSON 补充说明。
说明与签名分别记录出处，不把补充文档伪装成导出 XML 的原文。

## 自动化验证

原第一版为 20 项测试；可移植性修订后 `uv run pytest -q`：26 项测试通过。

测试覆盖继承与覆盖、重载、默认参数、信号、枚举、弃用和实验状态、
中文别名与英文 API、来源范围与路径约束、快照隔离、查询过程中切换基线、
断网、源码提交不匹配、发布中断、同步互斥、子进程超时、
官方归档提交与路径校验、Windows 长路径、用户配置保留、
缓存资料重建索引，以及 MCP 客户端的结构化返回与错误处理。

`ruff check src tests scripts` 和 `ruff format --check src tests scripts` 通过。
Skill 源文件与用户级安装副本均通过 `quick_validate.py`。

## 实际资料与 MCP

`scripts/verify_live.py` 使用官方 SDK 客户端启动真实 stdio 服务并完成握手，
发现全部 8 个工具，读取默认快照并查询：

| 用例 | 结果与来源 |
| --- | --- |
| `Node._ready` | 返回实际导出签名及完整说明，说明位于 `engine/doc/classes/Node.xml:109-117` |
| `Node.call_deferred` | 正确定位继承声明者 `Object` |
| 生命周期 | 找到 `docs/tutorials/scripting/scene_tree.rst` 与节点通知说明 |
| 线程安全 | 找到 `docs/tutorials/performance/thread_safe_apis.rst`，包括活动场景树限制及延迟调用依据 |
| 渲染器条件 | 找到 `docs/tutorials/rendering/renderers.rst`，包含 Compatibility、Mobile、Forward+ 条件 |
| 中文“线程安全” | 返回线程安全资料和相关 API |
| 来源回读 | 通过 `_ready` 的来源 ID 读取匹配源码 XML |

原始验收结果保存在不纳入 Git 的 `data/validation.json`。复验：

```sh
uv run python -X utf8 scripts/verify_live.py --data ./data --output ./data/validation.json
```

查询工具返回证据，不自动将手册片段改写成已验证结论。限制判断仍需阅读上下文；
资料不足时标记 `unconfirmed`。中文支持是主题别名检索，不是语义模型。
本次验证的是知识查询、版本与资料管理流程，没有运行或画面验证游戏项目。

## 本机接入

- 已安装用户级 `godot-knowledge` Skill，目标目录由 `CODEX_HOME` 或用户主目录发现。
- 已注册并启用 `godot-knowledge` MCP，启动环境与资料目录由本机安装时生成。
- 启动超时 30 秒，工具超时 900 秒。
- 原 Codex 配置首次修改前已保存 `.toml.before-godot-knowledge` 备份，
  其他 MCP 与用户设置保留。
- 新聊天可发现安装的 Skill 和 MCP；本次已通过独立 SDK 客户端验证连接。

开发期间失败或中断的候选保留在 `data/staging/` 供诊断；它们没有被设为默认快照。
前一个成功快照同样保留，便于比较与回退。

## 可移植性修订

Skill、安装入口和通用说明已移除开发者的目录与用户名。
安装入口为 `godot-knowledge install`；解释器从当前 Python 环境发现，
Skill 随 wheel 分发，默认资料目录由系统用户数据位置决定，CLI 与 MCP 一致。
引擎支持显式配置、环境变量、PATH 和 macOS 应用包。

新增验证覆盖目录优先级、任意工作目录、独立 MCP 入口、快照目录迁移、
不同解释器布局和 wheel 在源码目录外的独立安装。
wheel 的隔离安装、包内 Skill 安装及实际资料查询均已在本机通过；
原有 8 个工具的真实 MCP 验收也已复验通过。
已提供三个操作系统的 CI 矩阵；当前本机运行环境为 Windows，
Linux/macOS 原生验证需要相应 CI 实际运行，不能视为已经通过。
