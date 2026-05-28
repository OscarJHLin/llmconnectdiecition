# NetConnect macOS Node

macOS 子节点安装包 - 包含网络子节点和计算子节点功能

## 功能特性

- ✅ 网络子节点：自动发现中心路由器，支持内网多播通信
- ✅ 计算子节点：支持 AI 推理任务处理
- ✅ Web UI：可视化配置和状态监控
- ✅ 自动扫描：自动检测 Ollama、vLLM、LM Studio 等 AI 后端

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动节点

```bash
python main.py
```

### 3. 访问 Web UI

打开浏览器访问：http://localhost:8080

## 使用说明

1. **基本配置**：设置节点名称、组播地址和端口
2. **启动节点**：点击"启动节点"按钮开始运行
3. **查看状态**：在仪表盘查看路由器连接状态和任务完成情况
4. **聊天测试**：在聊天标签页测试 AI 功能

## 系统要求

- macOS 10.15+
- Python 3.8+
- 支持的 AI 后端：Ollama、vLLM、LM Studio

## 端口说明

- Web UI：8080
- 组播发现：224.0.0.1:5000
- 路由器连接：8888

## 目录结构

```
macos/
├── main.py          # 主程序（包含网络和计算功能）
├── requirements.txt # Python依赖
└── README.md        # 说明文档
```