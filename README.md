# 内网多AI协作系统

一个基于内网通信的多AI协作系统，支持无网络环境下的设备间实时通信、任务分发和结果融合。

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              内网环境                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    中心网络节点 (路由器/服务器)                      │    │
│  │  - 内网发现 (Multicast)                                            │    │
│  │  - 节点注册与管理                                                  │    │
│  │  - 消息路由与转发                                                  │    │
│  └───────────────────────────┬───────────────────────────────────────┘    │
│                              │                                             │
│         ┌────────────────────┼────────────────────┐                        │
│         ▼                    ▼                    ▼                        │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                 │
│  │   子计算节点 │    │   子计算节点 │    │   子计算节点 │                 │
│  │  (macOS)    │◄───►│ (Windows)   │◄───►│ (Android)   │                 │
│  │  - 网络+计算 │    │  - 网络+计算 │    │  - 网络+计算 │                 │
│  └──────────────┘    └──────────────┘    └──────────────┘                 │
│         │                    │                    │                         │
│         └────────────────────┼────────────────────┘                         │
│                              │                                             │
│                    ┌─────────▼─────────┐                                   │
│                    │   中心计算节点     │                                   │
│                    │  (Ubuntu Server)  │                                   │
│                    │  - 任务分发       │                                   │
│                    │  - AI推理         │                                   │
│                    │  - 结果融合       │                                   │
│                    └───────────────────┘                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 快速开始（按设备选择）

### 1. 中心网络节点（仅命令行）

下载 `packages/central-network/` 文件夹到服务器：

```bash
cd packages/central-network
python main.py
```

### 2. 中心计算节点（带 Web UI）

下载 `packages/central-compute/` 文件夹到服务器：

```bash
cd packages/central-compute
pip install -r requirements.txt
python main.py
# 访问: http://localhost:8081
```

### 3. macOS 子节点（带 Web UI）

下载 `packages/macos/` 文件夹：

```bash
cd packages/macos
pip install -r requirements.txt
python main.py
# 访问: http://localhost:8080
```

### 4. Windows 子节点（带 Web UI）

下载 `packages/windows/` 文件夹：

```powershell
cd packages\windows
pip install -r requirements.txt
python main.py
# 访问: http://localhost:8080
```

### 5. Linux 子节点（带 Web UI）

下载 `packages/linux/` 文件夹：

```bash
cd packages/linux
pip install -r requirements.txt
python main.py
# 访问: http://localhost:8080
```

### 6. Android 子节点（带 Web UI）

下载 `packages/android/` 文件夹：

```bash
# Termux 环境
pkg update && pkg install python
pip install -r requirements.txt
python main.py
# 访问: http://localhost:8080
```

## 项目结构

```
.
├── packages/                    # 独立安装包（按平台分离）
│   ├── central-network/         # 中心网络节点（路由器，命令行）
│   │   ├── main.py
│   │   └── README.md
│   ├── central-compute/         # 中心计算节点（Web UI）
│   │   ├── main.py
│   │   ├── requirements.txt
│   │   └── README.md
│   ├── macos/                   # macOS 子节点（网络+计算融合）
│   │   ├── main.py
│   │   ├── requirements.txt
│   │   └── README.md
│   ├── windows/                 # Windows 子节点（网络+计算融合）
│   │   ├── main.py
│   │   ├── requirements.txt
│   │   └── README.md
│   ├── linux/                   # Linux 子节点（网络+计算融合）
│   │   ├── main.py
│   │   ├── requirements.txt
│   │   └── README.md
│   └── android/                 # Android 子节点（网络+计算融合）
│       ├── main.py
│       ├── requirements.txt
│       └── README.md
│
├── central/                     # 旧版中心节点（保留）
├── hermes-agent-main/           # Hermes Agent 项目（可选）
├── examples/                    # 示例脚本
└── README.md                    # 本文件
```

## 各平台下载清单

| 设备类型 | 需要下载的文件夹 | 是否带 Web UI |
|----------|-----------------|---------------|
| 中心网络节点 | `packages/central-network/` | ❌ 命令行 |
| 中心计算节点 | `packages/central-compute/` | ✅ |
| macOS 子节点 | `packages/macos/` | ✅ |
| Windows 子节点 | `packages/windows/` | ✅ |
| Linux 子节点 | `packages/linux/` | ✅ |
| Android 子节点 | `packages/android/` | ✅ |

## 安装依赖

所有子节点都需要安装：

```bash
pip install -r requirements.txt
```

## 功能特性

### 子节点（macOS/Windows/Linux/Android）
- ✅ 网络子节点：自动发现中心路由器
- ✅ 计算子节点：AI 推理任务处理
- ✅ Web UI：可视化配置和状态监控
- ✅ 聊天功能：与 AI 对话

### 中心计算节点
- ✅ 任务分发：向子节点分发计算任务
- ✅ 子节点监控：实时监控所有连接的子节点
- ✅ 聊天功能：与中心 AI 对话
- ✅ 消息网关：飞书、微信集成配置

### 中心网络节点
- ✅ 多播发现：自动发现局域网内子节点
- ✅ 消息路由：转发节点间消息
- ✅ 节点管理：维护连接状态和心跳检测

## 启动顺序

1. **先启动中心网络节点**（路由器）
2. **再启动中心计算节点**（Ubuntu 服务器）
3. **最后启动各子节点**（macOS/Windows/Linux/Android）

子节点会自动通过 Multicast 发现中心节点并注册。

## 端口说明

| 端口 | 用途 |
|------|------|
| 8888 | 节点通信端口 |
| 5000 | Multicast 发现端口 |
| 8080 | 子节点 Web UI |
| 8081 | 中心计算节点 Web UI |

## 支持的 AI 后端

| 后端 | 默认端口 | 说明 |
|------|----------|------|
| Ollama | 11434 | 轻量级本地模型运行器 |
| vLLM | 8000 | 高性能 LLM 服务 |
| LM Studio | 1234 | 桌面端 AI 客户端 |
| OpenAI | 443 | OpenAI API 兼容 |

## 技术栈

- **通信**: TCP + UDP Multicast
- **Web UI**: Python http.server + HTML/CSS/JavaScript
- **AI 接口**: requests (REST API)
- **配置**: JSON

## 许可证

MIT License