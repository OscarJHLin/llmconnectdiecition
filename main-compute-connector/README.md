# NetConnect Main Compute Node - 连接器版本

主计算节点 - 通过 API/WebSocket 连接已有的 Hermes Agent 实例

## 功能特性

- ✅ 连接已有 Hermes：通过 URL/WebSocket 连接外部 Hermes Agent
- ✅ 任务分发：向子节点分发计算任务
- ✅ 子节点监控：实时监控所有连接的子节点状态
- ✅ 聊天功能：与中心 AI 进行对话
- ✅ 消息网关：支持飞书、微信等平台集成
- ✅ Web UI：可视化管理控制台

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动节点

```bash
python main.py
```

### 3. 访问管理控制台

打开浏览器访问：http://localhost:8081

### 4. 连接 Hermes Agent

在"Hermes连接"标签页输入 Hermes Agent 的 URL 并点击连接

## 使用说明

1. **设置**：配置节点名称和网络端口
2. **启动节点**：点击"启动节点"按钮开始运行
3. **连接 Hermes**：在"Hermes连接"页面输入外部 Hermes Agent 地址
4. **子节点监控**：查看所有已连接的子节点状态
5. **任务管理**：提交和管理计算任务

## 系统要求

- Ubuntu 20.04+（推荐）
- Python 3.8+
- 已运行的 Hermes Agent 实例

## 端口说明

- Web UI：8081
- 节点通信：8888
- 组播发现：224.0.0.1:5000

## 目录结构

```
main-compute-connector/
├── main.py          # 主程序（连接器版本）
├── requirements.txt # Python依赖
└── README.md        # 说明文档
```
