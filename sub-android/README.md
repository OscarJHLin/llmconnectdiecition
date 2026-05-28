# NetConnect Android Sub Node

Android 子节点 - 包含网络子节点和计算子节点功能

## 功能特性

- ✅ 网络子节点：自动发现主路由器，支持内网多播通信
- ✅ 计算子节点：支持 AI 推理任务处理
- ✅ Web UI：移动端优化的可视化界面
- ✅ 自动扫描：自动检测 Ollama、vLLM、LM Studio 等 AI 后端
- ✅ 聊天功能：与本地 AI 对话
- ✅ 轻量级设计：适合移动设备运行

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

在浏览器中访问：http://localhost:8080

## 使用说明

1. **AI后端配置**：选择AI后端类型，点击自动扫描或手动输入模型名称
2. **网络配置**：设置节点名称、组播地址和端口
3. **启动节点**：点击"启动节点"按钮开始运行
4. **查看状态**：在仪表盘查看路由器连接状态和任务完成情况
5. **聊天测试**：在聊天标签页测试 AI 功能

## 系统要求

- Android 7.0+（通过 Termux 运行）
- Python 3.8+
- 建议在同一局域网内运行

## 端口说明

- Web UI：8080
- 组播发现：224.0.0.1:5000
- 路由器连接：8888

## 目录结构

```
sub-android/
├── main.py          # 主程序（网络+计算融合）
├── requirements.txt # Python依赖
└── README.md        # 说明文档
```
