# ensp-lab

[English](README.md) | [简体中文](README.zh-CN.md)

用命令行（以及 Claude Code skill）批量配置和验证华为 eNSP 实验设备。

eNSP 会为每台已启动的设备在 `127.0.0.1` 上开一个 TCP 控制台端口，从 2000 起
逐个递增。这个 socket 就是设备真正的 VRP 命令行，所以配置可以用脚本下发和
校验，不必在图形界面里一条条敲。

无第三方依赖，Python 3.10+ 标准库即可。

> **非官方项目。** 与华为无隶属、无背书、无支持关系。本仓库不含任何华为软件、
> 设备镜像或厂商文件，不绕过任何授权或激活机制，也不会连接华为服务器。
> 你需要自己安装并授权 eNSP。详见 [NOTICE.md](NOTICE.md)。

## 它不做什么

它不建拓扑、不启动设备。这两件事是 eNSP 图形界面通过 VirtualBox 完成的，没有
可靠的 API。请先在 eNSP 里搭好拓扑并启动设备，再用这个工具接管。

## 安装

```bash
git clone https://github.com/<your-account>/ensp-lab.git
cd ensp-lab
python -m unittest discover -s tests    # 不需要 eNSP
```

作为 Claude Code skill 使用时，把仓库复制或软链到 skills 目录：

```bash
# Windows
xcopy /E /I ensp-lab %USERPROFILE%\.claude\skills\ensp-lab
# macOS / Linux
ln -s "$PWD/ensp-lab" ~/.claude/skills/ensp-lab
```

然后直接对 Claude 说「配一下 OSPF」「验证 BGP 邻居状态」。

## 用法

凡是按设备名下发的命令都要带 `--topo`，这样才能把 `R1` 解析成正确的控制台端口。

```bash
# 1. 实验环境起来了吗？
python scripts/ensp.py ports --topo lab.topo

# 2. 设备上现在是什么配置？
python scripts/ensp.py exec R1 "display current-configuration" --topo lab.topo

# 3. 下发配置（纯 VRP，一行一条命令，# 和 ! 是注释）
python scripts/ensp.py config R1 examples/configs/ospf_single_area/R1.cfg --topo lab.topo

# 4. 验证
python scripts/ensp.py verify examples/checks/ospf_single_area.json --topo lab.topo
```

```
$ python scripts/ensp.py ports --topo lab.topo
PORT   NAME MODEL        STATUS
2000   R1   AR1220       running
2001   R2   AR1220       running
2002   R3   AR1220       not started
```

```
$ python scripts/ensp.py verify examples/checks/ospf_single_area.json --topo lab.topo
ok   R1: OSPF neighbour R2 is Full
ok   R2: OSPF has two neighbours
ok   R3: learned R1 loopback as OSPF
ok   R1: learned R3 loopback as OSPF
ok   R1: ping R3 loopback
ok   R1: LSDB holds router LSAs

6 passed, 0 failed
```

没有 `.topo` 文件时，直接给控制台端口号：

```bash
python scripts/ensp.py exec 2000 "display version"
python scripts/ensp.py ports --first 2000 --last 2010
```

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 有命令或检查失败 |
| 2 | 连不上，或拓扑文件读不了 |

非零退出码让这些命令可以直接用在循环或 CI 式检查里。

## 配置文件

纯 VRP，一行一条命令。空行、`#` 和 `!` 会被忽略。脚本会自动把整个文件包在
`system-view` … `return` 之间，并在最后保存。

```text
# R1
sysname R1

interface LoopBack0
 ip address 10.0.1.1 255.255.255.0

interface GigabitEthernet0/0/1
 ip address 10.0.12.1 255.255.255.0

ospf 1 router-id 10.0.1.1
 area 0.0.0.0
  network 10.0.1.0 0.0.0.255
  network 10.0.12.0 0.0.0.255
```

加 `--no-save` 只改运行配置，不动 flash。

## 检查文件

`expect` 里的每个字符串都出现、且 `reject` 里一个都没出现，这条检查才算通过。

```json
{
  "checks": [
    {
      "device": "R1",
      "name": "learned R3 loopback as OSPF",
      "command": "display ip routing-table",
      "expect": ["10.0.3.0/24", "OSPF"],
      "reject": ["Error"]
    },
    {
      "device": "R1",
      "name": "ping R3 loopback",
      "command": "ping -c 2 10.0.3.3",
      "expect": ["2 packet(s) received"]
    }
  ]
}
```

检查应该证明**功能通了**——邻居状态、路由来源、ping 通——而不是证明某行文字被
写进了配置。

## 目录结构

```
SKILL.md                     Claude Code skill 说明
scripts/ensp_lib.py          控制台传输、拓扑解析、设备发现
scripts/ensp.py              CLI：ports / exec / config / verify
examples/configs/            静态路由、OSPF（单区/多区）、BGP、VLAN，
                             campus_vrrp_lacp（双核心 + VRRP + LACP + STP）
examples/checks/             配套的验证计划
references/device-catalog.md 各 eNSP 型号、接口命名、PC 配置方法
references/topo-format.md    .topo XML 格式
references/vrp-cookbook.md   常用 VRP 片段
tests/                       单元测试 + 假 VRP 设备
tests/fake_device.py         在固定端口跑一个假设备，手动联调用
tools/fix_vbox_path.py       修复安装后 eNSP 的 VBox 路径
NOTICE.md                    版权、商标与范围声明
```

## 工作原理

`ensp_lib.Console` 是一个很小的 telnet 客户端：连接、应答 `Press ENTER` 提示、
处理登录提示、识别 VRP 提示符、关闭分页。读取由提示符检测驱动，所以命令在设备
答完就返回，而不是固定 sleep。`---- More ----` 会自动翻页，`[Y/N]` 确认会自动
应答。

拓扑解析直接读 `.topo` XML，把设备名映射到控制台端口，不用自己查哪个端口是
哪台路由器。

## 测试

测试不需要 eNSP，在 Linux、macOS、Windows 上都能跑（Python 3.10+），CI 三个
平台都跑。

## 不装 eNSP 也能测

测试套件里带一个说同样协议的假 VRP 设备，覆盖提示符识别、分页、保存确认和错误
上报：

```bash
python -m unittest discover -s tests -v
```

想手动对着它跑 CLI：

```bash
python tests/fake_device.py 2000 R1                    # 终端 1
python scripts/ensp.py exec 2000 "display version"     # 终端 2
```

## 踩过的坑

这些现在都有测试覆盖了，但在真机上第一次遇到时会浪费不少时间。

**`save` 撑不过关闭拓扑。** VRP 的 `save` 写的是运行时的虚拟 flash，位置在
`%LOCALAPPDATA%\eNSP\VBoxServer\workspaces\<guid>\` 下，eNSP 关闭拓扑时会删掉。
只有 *File → Save Topology*（保存拓扑）才会把 flash 镜像写回 `.topo` 所在目录。
实验「重开就丢配置」，原因就在这里。

**PC 的设置在 `.topo` 文件里，不在设备上。** `PC` 没有控制台，它的地址是
`<dev>` 元素的 `-simpc_ip` / `-simpc_mask` / `-simpc_gateway` 属性。改的时候
必须先在 eNSP 里关掉拓扑，否则 eNSP 会用内存里的状态把文件覆盖回去。

**事件日志会干扰提示符识别。** VRP 会把 `DATASYNC_CFGCHANGE`、链路 up/down 之类
的日志异步打进命令输出中间。`config` 会先发 `undo terminal monitor`；跑长时间的
`exec` 会话时也建议先发一次。

**Eth-Trunk 成员口要求 trunk 先存在。** 在端口上敲 `eth-trunk 1`，如果
`interface Eth-Trunk1` 还没建，会报 `The trunk port does not exist`。`config`
现在会按需建 trunk 再重试，所以片段顺序不再要紧。

**接口视图的提示符里有斜杠。** 接口视图下提示符是
`[L1-GigabitEthernet0/0/1]`，所以匹配提示符的正则必须接受 `/`。

**eNSP 图形界面无法用模拟输入驱动。** eNSP 以管理员权限运行，Windows UIPI 会
静默丢弃非提权进程发来的鼠标键盘事件。不会报错，点击就是没反应。要改就改
`.topo` 文件。

## 限制

- 设备名来自 `.topo` 文件。用 `sysname` 改过名的设备在 `ports` 里显示新名字，
  通常正是你想要的，但 `--topo` 解析用的是拓扑里的名字。`三层交换机L2` 这类
  本地化标签也能从短名解析，只要匹配结果唯一。
- 没有 VRP 命令行的设备（`PC`、`Laptop`、`Cloud`、`Hub`、`MCS`、`STA`、`AP`、
  `Client`、`Server`、`Cellphone`、`FRSW`）无法配置。
  `references/device-catalog.md` 列了 eNSP 提供的全部型号。
- 同一台设备同一时间只能有一个控制台会话，不要并行对它跑两条命令。
- eNSP 的控制台端口按设备创建顺序分配，对同一个拓扑是稳定的，但增删设备后会变。

## 适用范围与免责声明

本工具操作的是 eNSP 为**你自己启动的**设备在 `127.0.0.1` 上开放的控制台端口。
它不附带任何华为软件、固件或设备镜像，不修改也不绕过授权或激活机制，不会向
华为发起任何网络请求。Huawei、eNSP、VRP 是华为技术有限公司的商标；本项目为
非官方项目，与华为无隶属关系。请仅用于自己的实验环境，并遵守你所安装的 eNSP
的许可条款。

完整声明见 [NOTICE.md](NOTICE.md)。

## 许可证

MIT，见 [LICENSE](LICENSE)。Copyright (c) 2026 dashen491。
