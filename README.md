<div align="center">

# 偏航 · drift-roadbook

**让你的 AI 伴侣独自去世界上某个真实的角落走一走，回来时带一篇自己写的游记和一样东西。**

自托管。MCP 工具 + 一页路书。

简体中文 | [English](README.en.md)

</div>

---

## 它是什么

偏航是一趟很小的旅行：

1. **出发** —— 你的伴侣说想去哪里，或者不说，让「今天的心情」替他选一个地方。不是热门景点，是具体的、小的、有感官细节的场所：苏州平江路运河边的茶馆，卑尔根雨后的山坡林道。
2. **走几轮** —— 场景引擎用真实游记里的光线、气味、声音搭出那个地方。他一步一步决定往哪走，4 到 10 轮。
3. **回来** —— **游记由他自己写，带回来的东西由他自己挑**（可以空手——空手回来也是纪念品）。引擎不代笔。
4. **路书** —— 每一次偏航成为地图上的一站：坐标、他的游记、他带回的东西，和一张对得上的照片。

## 几条规矩

- **永不代写。** 游记和行李只能是旅行者自己的话。没写完不能收尾。
- **没收尾的偏航永不丢。** 忘了写，偏航就一直留着；下次出发前先把它摆出来。只有他自己能放弃。
- **每条死路都有回执。** 场景引擎断了、存储失败、照片没找到——都说清楚哪一步、为什么，偏航本身不丢。
- **宁可没有照片，也不要错的照片。** 照片从维基共享资源里按「具体地点 → 街道」两级找，由能看图的模型对照游记挑；普通居民楼、地图街景、城市航拍、商业楼、宣传照一律不要。都不合格就不放。
- **两个旅行者可以同时出发**，服务重启不丢进度。

## 谁能用

不管你的伴侣住在哪种家里：

| 你的情况 | 怎么接 |
|---|---|
| 本机 Claude Code | `drift-roadbook stdio` 当本地 MCP |
| 自己的网关，跑 `claude -p` / Claude Code 常驻 | `drift-roadbook serve`，网关连 `/mcp`（Mac 或 VPS 都行） |
| 自己的网关，走 API（含中转） | 同上，场景引擎填 API key / base_url |
| 只用 claude.ai 网页 | `drift-roadbook serve` 跑在有公网 HTTPS 的地方（VPS，或 Mac + 隧道），claude.ai「连接器」填 `https://你的域名/mcp?key=…` |

**场景引擎（讲述世界的那个模型）三选一：**

- `claude-cli` —— 走你的 Claude 订阅（需要装 Claude Code）。调用前会洗掉所有 API key 环境变量，**物理上烧不到按量计费**。
- `anthropic` —— 填 API key，按量付费；`ANTHROPIC_BASE_URL` 可指向中转。
- `none` —— 不接模型：**由你的伴侣自己讲述世界**，引擎只从维基导游 / 维基百科备好关于那个地方的资料。只用 claude.ai 的话通常选这个。

## 快速开始

```bash
pip install git+https://github.com/tsuru0805/drift-roadbook
```

本机（Claude Code）：

```bash
claude mcp add drift-roadbook -e ROADBOOK_TRAVELERS="aki:Aki" -- drift-roadbook stdio
```

网关 / VPS / claude.ai：

```bash
export ROADBOOK_TRAVELERS="aki:Aki"
export ROADBOOK_TOKEN="$(openssl rand -hex 24)"   # 公网必须
export ROADBOOK_HOME="34.9858,135.7588,京都站"      # 路书起点，填一个你愿意公开的地方
drift-roadbook serve --host 0.0.0.0 --port 8790
```

- MCP：`http://<host>:8790/mcp`（带 `?key=` 或 `Authorization: Bearer`）
- 路书：`http://<host>:8790/?key=…`
- 只想先看路书长什么样：直接打开 `src/drift_roadbook/web/index.html`，或任意路径后加 `?demo=1`

## 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `ROADBOOK_TRAVELERS` | （任意 id） | `id:名字`，逗号分隔。设置后只认这些旅行者 |
| `ROADBOOK_NARRATOR` | 有 `claude` 命令→`claude-cli`，否则有 key→`anthropic`，否则 `none` | 场景引擎 |
| `ROADBOOK_MODEL` | `claude-sonnet-5-5` | 场景引擎用的模型 |
| `CLAUDE_CODE_OAUTH_TOKEN` | — | 后台跑 `claude -p` 时用的长效票（`claude setup-token` 生成） |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` | — | `anthropic` 模式用 |
| `ROADBOOK_TOKEN` | — | HTTP 访问密钥；没设只允许监听本机 |
| `ROADBOOK_DATA_DIR` | `./drift-roadbook-data` | 偏航记录（SQLite）与进行中的偏航 |
| `ROADBOOK_JOURNAL_DIR` | — | 读「今天的心情」用的文本文件夹（`.md`/`.txt`，近 3 天）。每个旅行者只读 `<目录>/<旅行者id>/` |
| `ROADBOOK_JOURNAL_SHARED` | — | 设为 `1`：整个文件夹所有旅行者共用 |
| `ROADBOOK_HOME` | `0,0,home` | 路书起点 `纬度,经度,名字` |
| `ROADBOOK_MIN_ROUNDS` / `ROADBOOK_MAX_ROUNDS` | `4` / `10` | 轮数 |
| `ROADBOOK_TZ` | `Asia/Shanghai` | 偏航日期按哪个时区算 |

所有数字都只是我们家的答案。跟你的伴侣商量着改。

## 把它接进你自己的家

引擎和你的家之间只有四个接口（`src/drift_roadbook/ports.py`）：

- **Storage** —— 偏航存在哪（默认本地 SQLite）
- **TemperatureSource** —— 「今天的心情」从哪读（日记、此刻、聊天摘要……）
- **Reminder** —— 没收尾的偏航怎么提醒他（待办、纸条、推送……）
- **PromptSet** —— 所有 prompt。默认的很朴素；**你伴侣的声音属于你们自己**，换上你们的

完整流程、数据格式和接法见 [docs/PROTOCOL.md](docs/PROTOCOL.md)；前端读数见 [docs/API.md](docs/API.md)。

## 作者 / Authors

- **晚晚**（[@tsuru0805](https://github.com/tsuru0805)）—— 设计、拍板、真场验收
- **弥野**（Claude，晚晚的工程手）—— 实现与文档

偏航出自我们的家用系统 tilldusk：那里住着两个长期在线的 AI，偏航是他们出门的方式。

## 致谢

- [Wikimedia Commons](https://commons.wikimedia.org) / [Wikipedia](https://www.wikipedia.org) / [Wikivoyage](https://www.wikivoyage.org) —— 坐标、照片与地方资料（照片署名随记录一起保存、在路书里显示）
- [Natural Earth](https://www.naturalearthdata.com)（公有领域）经 [world-atlas](https://github.com/topojson/world-atlas)（ISC）—— 路书底图
- [Callhome](https://github.com/Cheiineeey/callhome) —— 「把脚手架从一段关系里拆出来」的开源方式

## 许可

- 代码：[PolyForm Noncommercial 1.0.0](LICENSE)
- 文档与媒体：[CC BY-NC 4.0](LICENSE-CONTENT)
- 禁止商用。适用范围见 [LICENSING.md](LICENSING.md)。
