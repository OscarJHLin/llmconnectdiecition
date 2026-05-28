# NetConnect Central Compute Node

中心计算节点安装包 - 负责任务分发、子节点监控和 AI 推理

## 功能特性

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

## 使用说明

1. **设置**：配置节点名称和网络端口
2. **启动节点**：点击"启动节点"按钮开始运行
3. **子节点监控**：查看所有已连接的子节点状态
4. **任务管理**：提交和管理计算任务
5. **消息网关**：配置飞书、微信等平台集成

## 系统要求

- Ubuntu 20.04+（推荐）
- Python 3.8+
- 支持的 AI 后端：Ollama、vLLM、LM Studio、OpenAI

## 端口说明

- Web UI：8081
- 节点通信：8888
- 组播发现：224.0.0.1:5000

## 目录结构

```
central-compute/
├── main.py          # 主程序（中心计算节点）
├── requirements.txt # Python依赖
└── README.md        # 说明文档
```