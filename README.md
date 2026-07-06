# UNO-Q Status Web

一个运行在 Arduino UNO-Q 开发板 Linux 侧的轻量系统状态面板。
通过浏览器实时查看 CPU、内存、磁盘、运行时间和主机名。

**这是 AI Vibe Coding Workshop 的演示项目**，用于展示 UNO-Q 作为 Linux
计算节点运行 Web 服务的能力。

---

## 功能

- 🔲 **CPU 使用率** — 实时百分比 + 进度条
- 🧠 **内存使用** — 已用/总量，自动换算 MB
- 💾 **磁盘使用** — 根分区 `/` 和 `/home` 分区分别展示
- ⏱️ **系统运行时间** — 自上次启动以来的时长
- 🏷️ **主机名** — 显示设备 hostname
- 🔄 **每 5 秒自动刷新**

---

## 技术栈

| 层 | 技术 |
|----|------|
| 运行时 | Node.js |
| Web 框架 | Express (唯一依赖) |
| 系统数据 | `os` 模块 + `df` 命令 |
| 前端 | 原生 HTML/CSS/JS，无框架 |

---

## 安装

```bash
# 1. 进入项目目录
cd workshop1-unoq-status-web

# 2. 安装依赖（仅 express）
npm install
```

---

## 启动

```bash
npm start
```

启动后会显示：

```
============================================
  UNO-Q Status Web 已启动
  本地访问:     http://localhost:3000
  局域网访问:   http://Group11-B.local:3000
  IP 访问:      http://<board-ip>:3000
============================================
```

---

## 访问方式

### 在 UNO-Q 本机

浏览器打开 `http://localhost:3000`

### 在同一局域网的其他设备

- **通过主机名**: `http://<hostname>.local:3000`（需要 mDNS 支持）
- **通过 IP**: `http://<板子IP地址>:3000`

> **注意**: 服务器绑定在 `0.0.0.0`，确保所有网络接口均可访问。

---

## 项目结构

```
workshop1-unoq-status-web/
├── server.js       # 核心文件（Express + API + HTML 页面）
├── package.json    # 项目配置
├── README.md       # 本文件
└── DevLog/         # 开发过程记录
```

---

## 数据来源

| 指标 | 来源 | 方法 |
|------|------|------|
| CPU 使用率 | `/proc/stat` (via `os.cpus()`) | 两次采样计算差值 |
| 内存 | `/proc/meminfo` (via `os.totalmem/freemem`) | 直接读取 |
| 磁盘 | `df -h / /home` 命令 | 解析输出 |
| 运行时间 | `/proc/uptime` (via `os.uptime()`) | 直接读取 |
| 主机名 | `os.hostname()` | 直接读取 |

---

## 已知限制

- CPU 使用率是瞬时采样值（200ms 窗口），不是长期平均
- 磁盘仅展示 `/` 和 `/home` 两个分区
- 无历史数据记录或图表
- 仅支持 HTTP（不支持 HTTPS）
- 不包含认证机制——仅限可信局域网内使用

---

## License

MIT
