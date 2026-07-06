# UNO-Q Status Web — 项目总结

**日期**: 2026-07-06
**项目**: Arduino UNO-Q 系统状态展示 Web App（AI Vibe Coding Workshop）

---

## 第一部分：工作说明

整个开发过程遵循 **Brainstorming → Design → Planning → Implementation → Debugging → Handoff** 的 Pipeline。

### 1. 需求分析与头脑风暴（Brainstorming）

- 探索项目上下文：空 Git 仓库、Node.js v24.18.0、aarch64 架构
- 与用户澄清技术偏好：单文件方案（教学导向）→ 用户选择 A
- 确认端口 3000 → 用户选择 A
- 产出：明确的技术约束和用户偏好

### 2. 设计方案（Design）

- 编写完整设计文档：架构图、技术选型、页面布局、API 设计、数据流、错误处理
- 用户反馈调整：
  - 刷新间隔 2s → 5s
  - 磁盘从单分区改为双分区（`/` + `/home`）
  - DevLog 从单文件改为文件夹
  - 强调 0.0.0.0 绑定，代码需适合教学
- 产出：`docs/superpowers/specs/2026-07-06-unoq-status-web-design.md`

### 3. 实施计划（Planning）

- 将设计拆解为 7 个 Task，每个 Task 含完整代码和验证步骤
- 自检：Spec 覆盖率、占位符扫描、类型一致性
- 产出：`docs/superpowers/plans/2026-07-06-unoq-status-web.md`

### 4. 代码实施（Implementation）

- Task 1: `package.json` + `npm install`（仅 express 1 个依赖）
- Task 2: `server.js` 骨架，Express 监听 `0.0.0.0:3000`
- Task 3: 数据采集函数 — `getCpuUsage()`（两次采样法）、`getMemoryInfo()`、`getDisksInfo()`
- Task 4: `/api/status` 路由 + 内嵌 HTML 仪表盘（纯 CSS/JS，无框架）
- Task 5: `README.md`（安装、启动、访问、限制）
- Task 6: `DevLog/2026-07-06.md` 开发记录
- Task 7: 端到端验证（API、HTML、端口绑定、字段完整性）
- 产出：可运行的 Web App（`server.js` ~200 行含注释）

### 5. 调试与修复（Debugging）

- 修复了 4 个运行期问题（详见第二部分）
- 添加了 EADDRINUSE 友好错误提示
- 添加了动态 LAN IP 检测（`getLanIP()`）
- 修复了磁盘分区显示逻辑

### 6. 文档与交接（Handoff）

- 补全 DevLog（第 6-11 轮）
- 编写本总结文档
- 产出：`DevLog/SUMMARY.md`

---

## 第二部分：开发过程中的问题

### 问题 1: "无法访问此页面"

- **现象**: 用户浏览器打开 `http://localhost:3000` 显示无法访问
- **根因**: 服务器未运行——验证完成后进程被停止
- **解决**: 在终端运行 `node server.js &` 启动后台服务。此后应在 `npm start` 后保持终端窗口打开

### 问题 2: `npm start` 报 EADDRINUSE

- **现象**: 运行 `npm start` 时报 `Error: listen EADDRINUSE: address already in use 0.0.0.0:3000`，栈追踪吓人
- **根因**: 旧的后台进程仍占用端口 3000
- **解决**:
  1. 临时：`fuser -k 3000/tcp` 释放端口
  2. 长期：在 `server.js` 中为 `app.listen()` 添加 `error` 事件处理，EADDRINUSE 时显示友好中文提示："端口已被占用！请先运行 fuser -k 3000/tcp"

### 问题 3: DNS 解析失败（DNS_PROBE_FINISHED_NXDOMAIN）

- **现象**: 浏览器访问 `http://Group11-B.local:3000` 报 DNS 解析失败
- **根因**: 当前局域网不支持 mDNS（Avahi/Bonjour），`.local` 域名无法解析
- **解决**:
  1. 运行 `hostname -I` 获取真实 IP：`10.212.166.12`
  2. 新增 `getLanIP()` 函数，使用 `os.networkInterfaces()` 动态检测局域网 IPv4 地址
  3. 启动横幅自动显示真实 IP，不再用 `<board-ip>` 占位符
  4. 用户使用 `http://10.212.166.12:3000` 访问

### 问题 4: 磁盘卡片显示重复

- **现象**: 两张磁盘卡片都显示相同数据（9.8G, 46%）
- **根因**: `df -h / /home` 中 `/home` 不是独立分区，两者指向同一文件系统。实际独立分区是 `/home/arduino`（`/dev/mmcblk0p69`, 18G）
- **解决**: 重写 `getDisksInfo()`——分别用 `df -h /` 和 `df -h $(os.homedir())` 各自查询，使用查询路径作为显示标签，不去重

---

## 第三部分：任务进度与交接

### 当前状态

| 项目 | 状态 |
|------|------|
| server.js | ✅ 完成，运行中 |
| 系统数据采集 | ✅ CPU / 内存 / 磁盘（双分区） / uptime / hostname |
| 前端仪表盘 | ✅ 深色主题，5 秒自动刷新，卡片动态渲染 |
| 错误处理 | ✅ EADDRINUSE 友好提示、API 异常捕获、前端断网提示 |
| 文档 | ✅ README + DevLog + SUMMARY |
| Git | ✅ main 分支，11 个提交 |

### 如何启动

```bash
cd /home/arduino/workshop1-unoq-status-web
npm start
```

启动后控制台显示真实 IP 地址，浏览器访问 `http://<显示的IP>:3000`。

如果端口被占用：
```bash
fuser -k 3000/tcp
npm start
```

### 项目文件结构

```
workshop1-unoq-status-web/
├── server.js                           # 核心（Express + API + HTML）
├── package.json                        # express 依赖
├── package-lock.json
├── README.md                           # 使用说明
├── .gitignore                          # node_modules
├── DevLog/
│   ├── 2026-07-06.md                   # 逐轮开发记录
│   └── SUMMARY.md                      # 本文件
└── docs/superpowers/
    ├── specs/2026-07-06-unoq-status-web-design.md   # 设计文档
    └── plans/2026-07-06-unoq-status-web.md          # 实施计划
```

### 技术要点（后续开发者须知）

1. **单文件架构**: 所有代码在 `server.js` 中，从上到下依次为：依赖引入 → 工具函数 → 数据采集 → API 路由 → HTML 页面 → 服务器启动
2. **CPU 采样**: `getCpuUsage()` 使用两次采样取差值法，第一次采样后等待 200ms 再采样，因此 API 调用有 200ms 延迟（这是正常的）
3. **磁盘查询**: 使用 `os.homedir()` 动态获取用户 home 目录路径，不硬编码 `/home/arduino`
4. **IP 检测**: `getLanIP()` 在启动时调用，跳过 lo 回环和 docker 虚拟接口，取第一个非内部 IPv4
5. **0.0.0.0 绑定**: 关键设置，缺少则仅本机可访问
6. **唯一依赖**: express 4.x，无其他 npm 包

### 已知限制

- CPU 使用率是瞬时采样值（200ms 窗口），不是长期平均
- 磁盘仅展示 `/` 和用户 home 目录两个路径
- 无历史数据记录或图表
- 仅支持 HTTP（不支持 HTTPS）
- 不包含认证机制——仅限可信局域网使用
- 不支持 mDNS（`.local` 域名），需使用 IP 地址访问

### 可能的后续方向

- 添加 WebSocket 替代轮询，降低延迟
- 添加 CPU 温度、网络流量等更多指标
- 添加历史数据折线图
- 将 HTML 抽离为独立文件，或使用模板引擎
- 添加 systemd service 文件实现开机自启
