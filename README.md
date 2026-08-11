# OKX 定投做空脚本（dtzk）v1.2

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

OKX 合约 DCA 脚本，支持**做空**和**做多**，按配置定时定投，自动补仓、风控监控、手机推送，适合长期定投策略。

## 快速开始

```bash
pip install python-okx requests questionary
python main.py
```

首次运行会自动引导登录和配置。配置保存在 `config.json`（含 API 密钥，已在 `.gitignore` 中排除）。仓库提供了 `config.example.json` 作为模板参考。

## 功能

| 功能 | 说明 |
|---|---|
| 多空双向 | 做空（sell）/ 做多（buy） |
| 定时定投 | 自定义日期范围、每天/工作日、多个时间点 |
| 委托价格可选 | 同向价1/5（post_only挂单）、对手价1/5（limit吃单），按深度档位计价 |
| 挂单被拒自动重试 | 同向价被交易所秒关后自动刷新盘口重新挂单，次数/间隔可配 |
| 自动补保证金 | 强平线未达设定值时自动追加，余额不足推送提醒 |
| 安全边际监控 | 周期性检查（间隔可配），gap 缩小趋势自动补仓，恢复后推送错过时段 |
| 系统设置 | 安全边际间隔、主循环间隔、成交等待超时、重试次数/间隔均可自定义 |
| 目标价止盈 | 做空：标记价 ≤ 目标价；做多：标记价 ≥ 目标价 |
| 手机推送 | Bark / Server酱 / PushPlus / Telegram，17 种场景全覆盖 |
| 定投统计 | 每段策略成功/跳过/失败/未成交次数，持久化存档 |

## 快速开始

### 方式一：打包好的 exe（Windows，无需装 Python）

1. 下载 `dtzk.exe`，放在一个空文件夹里
2. 双击运行，按提示登录和配置
3. 配置好后，命令行运行 `.\dtzk.exe --run` 即可无头执行

### 方式二：源码运行

```bash
pip install python-okx requests
python main.py
```

## 获取 OKX APIKey

1. 登录 OKX → API → 创建 APIKey（**建议先在模拟盘创建**）
2. 权限：**读取** + **交易**
3. 记录 `APIKey`、`SecretKey`、`Passphrase`

> ⚠️ `SecretKey` 只显示一次，`config.json` 含密钥，切勿外泄。
> 
> ⚠️ **不要开启 IP 白名单**。国内网络通过代理/VPN 访问 OKX，出口 IP 经常变动，开了白名单会导致 API 请求全部被拒。除非你用的是固定 IP 的海外服务器，否则保持白名单关闭。

## 网络与代理

OKX 不服务中国大陆 IP。本地跑需代理，脚本会沿用系统代理；也可在 `config.json` 显式指定：

```json
"runtime": { "proxy": "http://127.0.0.1:7890" }
```

部署到国外服务器无需代理。

## 使用流程

菜单 ↑/↓ 方向键选择，回车确认（无终端环境自动退回数字输入）：

1. **登录** → 填入 API 凭证
2. **合约配置** → 合约、逐仓/全仓、杠杆、数量、方向（sell=做空 / buy=做多）
3. **时间配置** → 日期范围、类型（每天/工作日）、定投时间点
4. **暂停配置** → 设定强平线（输入 `n` 关闭）、目标价格、安全边际
5. **推送配置** → 选渠道填凭证，可发测试消息
6. **执行策略** → 确认配置（会显示可用余额），开始执行，`Ctrl+C` 暂停
7. **定投统计** → 查看历史记录

配置保存到 `config.json`，日志写入 `dtzk.log`，统计写入 `stats.json`。

## 无头模式

跳过菜单，直接执行，适合服务器长期运行。

**Windows**（用 exe）：
```powershell
.\dtzk.exe --run
```

**Linux**：
```bash
python main.py --run
```

> 前提：先在本机交互跑一次完成配置，再把文件夹/exe 拷到服务器。

## 多开（同时运行多个合约策略）

同一 OKX 账户可以创建多个 API Key，每个 Key 独立限频，互不影响。只需把整个项目文件夹复制多份，每份配不同的 `config.json` 即可。

推荐目录结构：

```
dtzk/
├── xau/              ← 完整项目复制
│   ├── main.py
│   ├── config.json   ← XAU-USDT-SWAP, API Key A
│   └── ...
├── btc/
│   ├── main.py
│   ├── config.json   ← BTC-USDT-SWAP, API Key B
│   └── ...
└── eth/
    ├── main.py
    ├── config.json   ← ETH-USDT-SWAP, API Key C
    └── ...
```

每份 `cd` 到对应目录交互配置一次（登录 + 合约 + 时间），之后用 screen/tmux 同时启动：

```bash
screen -S xau
cd ~/dtzk/xau && python main.py --run
# Ctrl+A D 退出 screen

screen -S btc
cd ~/dtzk/btc && python main.py --run

screen -S eth
cd ~/dtzk/eth && python main.py --run
```

**Windows** 开多个终端窗口：

```powershell
cd D:\dtzk\xau
python main.py --run
```

```powershell
cd D:\dtzk\btc
python main.py --run
```

> 多实例建议把「系统设置 → 安全边际检测间隔」调到 60~120s，降低 API 请求总量。单台 2GB 服务器跑 10 个以内问题不大。

## 服务器部署

### 通用步骤（所有 Linux 发行版）

```bash
# 1. 装 Python
# Debian / Ubuntu
sudo apt update && sudo apt install python3 python3-pip python3-venv -y

# CentOS / RHEL
sudo yum install python3 python3-pip -y

# 2. 上传项目到服务器（本机执行）
scp -r ./* user@你的服务器IP:~/dtzk/

# 3. 服务器上创建虚拟环境并装依赖
cd ~/dtzk
python3 -m venv .venv
.venv/bin/pip install python-okx requests questionary

# 4. 交互配置一次（登录 + 合约 + 时间）
PYTHONIOENCODING=utf-8 .venv/bin/python main.py

# 5. 无头运行
.venv/bin/python main.py --run
```

> 第 4 步加 `PYTHONIOENCODING=utf-8` 是因为部分服务器默认 locale 是 ASCII，不加的话出错时中文报错信息会乱码。

### 后台运行（screen）

适合临时跑、调试期间用：

```bash
screen -S dtzk
cd ~/dtzk && .venv/bin/python main.py --run
# 按 Ctrl+A 然后按 D 退出 screen，脚本继续跑

# 回来看
screen -r dtzk

# 看所有 screen
screen -ls
```

### 开机自启（systemd）

适合长期部署，服务器重启后自动拉起：

```bash
sudo nano /etc/systemd/system/dtzk.service
```

写入以下内容：

```ini
[Unit]
Description=OKX DCA Short Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=你的用户名
WorkingDirectory=/home/你的用户名/dtzk
ExecStart=/home/你的用户名/dtzk/.venv/bin/python main.py --run
Environment=PYTHONIOENCODING=utf-8
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable dtzk
sudo systemctl start dtzk

# 看日志
journalctl -u dtzk -f
```

多实例的话复制 `.service` 文件改个名字就行，比如 `dtzk-xau.service`、`dtzk-btc.service`。

### 注意事项

- 合约有爆仓风险，**务必先用模拟盘验证**，实盘先小仓位试
- 做空：强平线 > 目标价
- 做多：强平线 < 目标价，且强平线不能大于标记价
- 服务器上 `chmod 600 config.json`

### 常见报错

脚本运行中遇到的报错分两类：**网络层**的和 **OKX 返回**的。

#### 网络层报错（Python 系统级，请求没发到 OKX）

| 报错 | 含义 | 常见原因 |
|------|------|---------|
| `[Errno 11004] getaddrinfo failed` | DNS 解析失败，连 OKX 域名都找不到 | 服务器在国内 / 没配代理 / DNS 挂掉 |
| `timed out` | 请求发出去了但没收到回复 | 网络不稳 / 代理延迟太高 |
| `Connection reset by peer` | OKX 那边主动断开连接 | 偶尔发生，重试就能恢复 |
| `Connection refused` | 端口不通 | 代理没开或配错了 |

遇到网络层报错脚本会自动重试 3 次，3 次都失败会在执行循环里抓下来推送手机，然后休眠一段时间继续跑，**不会崩**。

#### OKX 返回的错误码（请求到了，OKX 拒绝了）

| 错误码 | 含义 | 常见原因 |
|--------|------|---------|
| `50011` | 请求频率超限 | 多合约同时跑 / 安全边际间隔设太短，调大 `系统设置 → 检测间隔` |
| `50113` | 签名无效 / 时间戳错误 | 服务器刚开机 NTP 时间还没同步，等半分钟再跑 |
| `50111` | API Key 无效 | Key 输错了、被删了、或过期了 |
| `51000` | 参数错误 | 合约名写错了之类，一般不会遇到 |
| `50026` | OKX 系统内部错误 | OKX 自己的问题，等会就好 |

OKX 错误码在下单/补仓环节会直接推送手机通知，不会反复重试浪费请求额度。

#### 兜底机制

```
_retry(3次) → 执行循环(推送+继续) → 最外层(推送+退出+systemd 30s后重启)
```

三层兜底，任何漏网之鱼都会推到手机，脚本崩了 systemd 也会自动拉起来。

## v1.2 更新内容

- **委托价格可选**：合约配置新增价格模式选项——同向价1（卖一）/ 同向价5（卖五）/ 对手价1（买一）/ 对手价5（买五），用 OKX 官方 tickSz 按深度档位计算委托价。同向价自动用 post_only 挂单（maker 手续费更低），对手价用 limit 吃单
- **同向价挂单被拒自动重试**：post_only 挂单被交易所秒关后，自动刷新盘口重新以同向价挂单，直到成交或次数用完。每次重试独立计算委托价，避免盘口波动导致反复被拒
- **系统设置新增 3 项**：下单后等待成交超时（默认 60s）、同向价挂单被拒重试次数（默认 5 次）、重试间隔（默认 1s），全部自由输入
- **推送文案优化**：成交/超时/被拒消息更明确，超时推送标注"已成功挂单，确认存活"，被拒推送含手动补单提示
- **界面优化**：系统设置各参数增加详细说明，含时间点间距建议公式

## v1.1 更新内容

- **周期性安全边际监控**：安全边际检查独立于定投时间点，按可配置的间隔（30s/60s/2min/3min/5min/10min）持续监控，不再只在定投触发时才检查
- **gap 缩小趋势自动补仓**：检测到强平价与标记价差距在缩小时，自动触发补仓检查，无需定时轮询
- **下单前强制安全检查**：每次定投下单前强制检查安全边际，堵死周期性检查的窗口期
- **暂停错过定投通知**：因安全边际暂停而错过的定投时段，恢复后推送通知并计入统计（`paused`），提醒用户手动补单
- **系统设置菜单**：主菜单新增「系统设置」，可自定义安全边际检测间隔和主循环轮询间隔
- **输入提示优化**：所有输入框末尾加冒号，方便用户确认输入内容

## 常见问题

**Q：为什么我的定投时间点被跳过了？**

A：脚本是单线程串行执行的，每次下单后会阻塞等待成交（等待时长 = 系统设置里的「下单后等待成交超时」）。两个定投时间点的间隔必须大于 `同向价被拒重试次数 × 重试间隔 + 等待超时`，否则后面的时间点会被跳过。比如重试 5 次 × 1s + 等待 300s = 305s，那定投时间点至少间隔 6 分钟。

**Q：同向价和对手价有什么区别？**

A：同向价 = 跟你同方向的深度档位（做空参考卖一/卖五，做多参考买一/买五），用 post_only 挂单，只做 maker 不收 taker 手续费。对手价 = 跟你反方向的深度档位，用 limit 吃单，优先成交但手续费更高。推荐选同向价 1。

**Q：post_only 挂单为什么会被取消？**

A：下单瞬间盘口波动导致你的挂单价跨过了价差（做空时卖价 ≤ 买一价），交易所判定这会立刻成交变吃单，post_only 规则下直接拒掉。脚本会自动重试，刷新盘口后重新挂单。

**Q：超时推送了但后来订单成交了怎么办？**

A：脚本等待超时后会推送通知并回到主循环，不会回头再查。但订单本身在 OKX 上仍然有效，后续被对手盘吃掉就会正常成交，不影响你的仓位。推送里写的"已成功挂单，确认存活"就是这个意思。

**Q：国内服务器连不上 OKX 怎么办？**

A：OKX 不服务大陆 IP，必须配代理。在 `config.json` 的 `runtime.proxy` 里填代理地址，或者部署到海外服务器（推荐首尔，延迟最低）。

**Q：一台服务器能跑多个合约吗？**

A：可以，复制多份项目文件夹，每份配不同 API Key 和合约，用 screen/tmux 同时跑。多实例建议在系统设置里把检测间隔调大到 60~120s，降低 API 请求总量。2GB 服务器跑 10 个以内没问题。

**Q：订单显示 `'data'` 异常是什么？**

A：OKX 服务端偶发抖动，返回了不带 `data` 字段的响应。脚本会自动兜住并继续轮询，不影响订单执行。

## 免责声明

**本脚本仅供学习和技术交流，使用者自行承担一切交易风险。**

- 加密货币合约交易存在极高风险，可能导致全部本金损失甚至穿仓负债
- 脚本作者不提供任何投资建议，不对因使用本脚本产生的任何盈亏、爆仓、穿仓或资金损失承担责任
- 定投策略不能保证盈利，历史表现不代表未来收益
- 使用者应在**模拟盘**充分验证后再考虑实盘，实盘建议从小仓位开始
- 脚本不保证零 bug 或持续稳定运行，使用者应自行监控仓位并在必要时手动干预
- OKX API 的可用性和限制不在作者控制范围内，API 变更可能导致脚本功能异常
- 请自行评估风险承受能力，**不要投入你无法承受损失的资金**

## 作者

**梦中分解与 AI 助手 dsv4**

此脚本完全免费，旨在帮助喜欢做模式外的家人们管住手降低赌性。希望牧原🐷🐷一路长红，豆家军大获全胜。

如有 bug 联系 **QQ 2334947006**
