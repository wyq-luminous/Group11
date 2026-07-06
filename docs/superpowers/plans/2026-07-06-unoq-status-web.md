# UNO-Q Status Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-file Express web app that displays UNO-Q system status (CPU, memory, dual-disk, uptime, hostname) on a dark dashboard with 5-second auto-refresh.

**Architecture:** One `server.js` file containing Express server, data collection functions (using `os` module + `df`), API route (`/api/status`), and embedded HTML page. Listens on `0.0.0.0:3000` for LAN access. Only dependency: `express`.

**Tech Stack:** Node.js v24, Express 4.x, vanilla JS/CSS in embedded HTML, `os` + `child_process` built-in modules.

## Global Constraints

- Must listen on `0.0.0.0` (not just `127.0.0.1`) for LAN access
- Refresh interval: 5 seconds
- Two disk partitions: `/` and `/home`
- Only 1 npm dependency: `express`
- No database, no auth, no frameworks beyond Express
- Dark terminal-style dashboard UI
- All code in single file `server.js` with inline comments explaining data sources
- Port: 3000

## File Map

| File | Responsibility | Created/Modified |
|------|---------------|-----------------|
| `package.json` | Declare express dependency + start script | Create |
| `server.js` | Express server, data collection, API route, HTML page (~180 lines with comments) | Create |
| `README.md` | Installation, startup, access, limitations | Create |
| `DevLog/2026-07-06.md` | Development log: prompts, actions, responses | Create |

---

### Task 1: Project initialization — package.json and npm install

**Files:**
- Create: `package.json`

**Interfaces:**
- Consumes: nothing
- Produces: `package.json` with `express` dependency, `node_modules/` after install

- [ ] **Step 1: Write package.json**

```json
{
  "name": "unoq-status-web",
  "version": "1.0.0",
  "description": "UNO-Q system status dashboard — lightweight web app for AI Vibe Coding Workshop",
  "main": "server.js",
  "scripts": {
    "start": "node server.js"
  },
  "dependencies": {
    "express": "^4.21.0"
  },
  "license": "MIT"
}
```

- [ ] **Step 2: Run npm install**

Run: `npm install`
Expected: express and its dependencies installed into `node_modules/`, no errors.

- [ ] **Step 3: Commit**

```bash
git add package.json package-lock.json
git commit -m "chore: init project with express dependency"
```

---

### Task 2: Server skeleton — Express app with 0.0.0.0 listener

**Files:**
- Create: `server.js`

**Interfaces:**
- Consumes: `express` from node_modules (Task 1)
- Produces: Express app listening on `0.0.0.0:3000`, responds to `GET /` with plain text placeholder

- [ ] **Step 1: Write server.js skeleton**

```javascript
/**
 * UNO-Q Status Web — 系统状态展示 Web 服务
 *
 * 技术栈: Node.js + Express
 * 数据来源:
 *   os.cpus()     → CPU 使用率（两次采样取差值）
 *   os.totalmem() / os.freemem() → 内存使用情况
 *   os.uptime()   → 系统运行时间
 *   os.hostname() → 主机名
 *   df -h / /home → 磁盘使用情况（根分区 + /home 分区）
 *
 * 监听 0.0.0.0:3000，同一局域网内设备均可访问
 */

const express = require('express');
const os = require('os');

const app = express();
const PORT = 3000;

// ============================================================
// 路由: 首页
// ============================================================
app.get('/', (req, res) => {
  res.send('UNO-Q Status Web is running.');
});

// ============================================================
// 启动服务器 — 关键: 显式绑定 0.0.0.0
// 如果省略 host 参数，Express 默认只监听 127.0.0.1（本机回环），
// 局域网内其他设备将无法访问。
// 0.0.0.0 表示“监听本机所有网络接口”，包括 WiFi 和以太网。
// ============================================================
app.listen(PORT, '0.0.0.0', () => {
  console.log('============================================');
  console.log('  UNO-Q Status Web 已启动');
  console.log(`  本地访问:     http://localhost:${PORT}`);
  console.log(`  局域网访问:   http://${os.hostname()}.local:${PORT}`);
  console.log(`  IP 访问:      http://<board-ip>:${PORT}`);
  console.log('============================================');
});
```

- [ ] **Step 2: Start server and verify it responds**

Run: `node server.js`
Expected: Console prints startup banner with hostname and URLs.

Then in another terminal: `curl http://localhost:3000/`
Expected: `UNO-Q Status Web is running.`

Stop the server (Ctrl+C) after verifying.

- [ ] **Step 3: Verify 0.0.0.0 binding**

Run: `node server.js & sleep 1 && ss -tlnp | grep 3000`
Expected output includes `0.0.0.0:3000` (not `127.0.0.1:3000`).

Stop the server: `kill %1`

- [ ] **Step 4: Commit**

```bash
git add server.js
git commit -m "feat: add Express server skeleton with 0.0.0.0 binding"
```

---

### Task 3: System data collection functions

**Files:**
- Modify: `server.js` — add data collection functions after the `const PORT` line, before the routes

**Interfaces:**
- Consumes: `os` module (built-in), `child_process.execSync` (built-in)
- Produces:
  - `getCpuUsage()` → `Promise<number>` — CPU usage 0–100, two-sample diff over 200ms
  - `getMemoryInfo()` → `{ used: number, total: number, unit: 'MB' }` — used/total in MB
  - `getDisksInfo()` → `Array<{ mount: string, total: string, used: string, percent: number }>` — parsed `df -h` output

- [ ] **Step 1: Add child_process require and data functions to server.js**

Insert the following after the `const PORT = 3000;` line:

```javascript
const { execSync } = require('child_process');

// ============================================================
// 数据采集函数
// ============================================================

/**
 * 获取 CPU 使用率（百分比）
 *
 * 原理: CPU 使用率是瞬时值，无法直接读取一个“当前使用率”的数字。
 * 需要对 /proc/stat（通过 os.cpus() 暴露）做两次采样，
 * 计算两次采样之间 idle 时间占总时间的比例，反过来得到使用率。
 *
 * 第一步: 记录当前每个核心的 times (user, nice, sys, idle, irq)
 * 第二步: 等待 200ms 让 CPU 完成一些工作
 * 第三步: 再次记录每个核心的 times
 * 第四步: CPU使用率 = 100 - (idle差值 / total差值 * 100)
 */
function getCpuUsage() {
  return new Promise((resolve) => {
    const cpus1 = os.cpus();

    setTimeout(() => {
      const cpus2 = os.cpus();
      let idleDiff = 0;
      let totalDiff = 0;

      for (let i = 0; i < cpus1.length; i++) {
        const t1 = cpus1[i].times;
        const t2 = cpus2[i].times;

        const idle1 = t1.idle;
        const total1 = t1.user + t1.nice + t1.sys + t1.idle + t1.irq;

        const idle2 = t2.idle;
        const total2 = t2.user + t2.nice + t2.sys + t2.idle + t2.irq;

        idleDiff += idle2 - idle1;
        totalDiff += total2 - total1;
      }

      const usage = totalDiff === 0 ? 0 : 100 - (idleDiff / totalDiff) * 100;
      resolve(Math.round(usage * 10) / 10);
    }, 200);
  });
}

/**
 * 获取内存使用情况
 *
 * os.totalmem() → 系统总内存（字节）
 * os.freemem()  → 当前空闲内存（字节）
 * 已用 = 总量 - 空闲
 */
function getMemoryInfo() {
  const total = os.totalmem();
  const free = os.freemem();
  const used = total - free;

  return {
    used: Math.round(used / (1024 * 1024)),
    total: Math.round(total / (1024 * 1024)),
    unit: 'MB',
  };
}

/**
 * 获取磁盘使用情况（根分区 / 和 /home 分区）
 *
 * 通过 df -h 命令获取人类可读的磁盘信息，
 * 解析其输出为结构化数据。
 *
 * df -h 输出示例:
 * Filesystem      Size  Used Avail Use% Mounted on
 * /dev/mmcblk0p2  7.8G  1.2G  6.6G  15% /
 * /dev/mmcblk0p3   15G  3.4G   12G  23% /home
 */
function getDisksInfo() {
  try {
    const output = execSync('df -h / /home', { encoding: 'utf8' });
    const lines = output.trim().split('\n');

    // 跳过第一行（标题），解析后续的数据行
    return lines.slice(1).map((line) => {
      const parts = line.trim().split(/\s+/);
      if (parts.length < 6) return null;

      return {
        mount: parts[5],
        total: parts[1],
        used: parts[2],
        percent: parseInt(parts[4], 10),
      };
    }).filter(Boolean);
  } catch (err) {
    console.error('获取磁盘信息失败:', err.message);
    return [];
  }
}
```

- [ ] **Step 2: Verify functions work via Node.js REPL**

Run:
```
node -e "
const os = require('os');
const { execSync } = require('child_process');

// Test memory
console.log('Memory total (MB):', Math.round(os.totalmem() / (1024*1024)));
console.log('Memory free (MB):', Math.round(os.freemem() / (1024*1024)));
console.log('Hostname:', os.hostname());
console.log('Uptime (s):', os.uptime());

// Test disk
const out = execSync('df -h / /home', { encoding: 'utf8' });
console.log('Disk output:');
console.log(out);
"
```
Expected: Prints memory numbers, hostname, uptime, and df output for both partitions.

- [ ] **Step 3: Commit**

```bash
git add server.js
git commit -m "feat: add system data collection functions (CPU, memory, disks)"
```

---

### Task 4: API route and embedded HTML page

**Files:**
- Modify: `server.js` — add `GET /api/status` route and embedded HTML with CSS/JS

**Interfaces:**
- Consumes: `getCpuUsage()`, `getMemoryInfo()`, `getDisksInfo()` (Task 3), `os.uptime()`, `os.hostname()`
- Produces:
  - `GET /api/status` → JSON `{ cpu, memory, disks, uptime, hostname }`
  - `GET /` → full HTML dashboard page

- [ ] **Step 1: Add the /api/status route**

Insert after the data collection functions and replace the existing `GET /` route:

```javascript
// ============================================================
// API 路由: 返回系统状态 JSON
// ============================================================
app.get('/api/status', async (req, res) => {
  try {
    const [cpu, memory, disks, uptime, hostname] = await Promise.all([
      getCpuUsage(),
      getMemoryInfo(),
      getDisksInfo(),
      os.uptime(),
      os.hostname(),
    ]);

    res.json({ cpu, memory, disks, uptime, hostname });
  } catch (err) {
    console.error('API 错误:', err);
    res.status(500).json({ error: '无法获取系统状态' });
  }
});
```

Note: `getMemoryInfo()` and `getDisksInfo()` are synchronous, but wrapping everything in `Promise.all` keeps the route clean. Only `getCpuUsage()` is truly async (200ms delay).

- [ ] **Step 2: Add the embedded HTML page**

Replace the existing `GET /` route with the full HTML page. Insert after the `/api/status` route:

```javascript
// ============================================================
// 路由: 首页 HTML 页面
// 内嵌 CSS + JS，无需额外文件
// ============================================================
app.get('/', (req, res) => {
  res.send(`<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>UNO-Q System Status</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Courier New', monospace;
      background: #1a1a2e;
      color: #e0e0e0;
      min-height: 100vh;
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 16px;
    }
    .container { max-width: 960px; width: 100%; }
    h1 {
      text-align: center;
      font-size: 1.6rem;
      margin-bottom: 4px;
      color: #ffffff;
    }
    .subtitle {
      text-align: center;
      font-size: 0.9rem;
      color: #888888;
      margin-bottom: 24px;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .card {
      background: #16213e;
      border-radius: 12px;
      padding: 20px;
      border: 1px solid #0f3460;
    }
    .card-title {
      font-size: 0.85rem;
      color: #aaaaaa;
      margin-bottom: 12px;
    }
    .card-value {
      font-size: 1.8rem;
      font-weight: bold;
      color: #ffffff;
      margin-bottom: 8px;
    }
    .card-detail {
      font-size: 0.8rem;
      color: #888888;
      margin-bottom: 10px;
    }
    .progress-bar {
      height: 6px;
      background: #2a2a4a;
      border-radius: 3px;
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      border-radius: 3px;
      transition: width 0.5s ease;
    }
    .progress-fill.low    { background: #4caf50; }
    .progress-fill.medium { background: #ff9800; }
    .progress-fill.high   { background: #f44336; }
    .info-row {
      background: #16213e;
      border-radius: 12px;
      padding: 16px 20px;
      border: 1px solid #0f3460;
      margin-bottom: 12px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .info-label { color: #aaaaaa; font-size: 0.9rem; }
    .info-value { color: #ffffff; font-size: 0.95rem; font-family: 'Courier New', monospace; }
    .status-bar {
      text-align: center;
      font-size: 0.8rem;
      color: #666666;
      padding: 8px;
    }
    .status-bar.error { color: #f44336; }
  </style>
</head>
<body>
  <div class="container">
    <h1>&#x1F5A5;&#xFE0F; UNO-Q System Status</h1>
    <p class="subtitle" id="hostname-display">...</p>

    <div class="cards" id="cards-container">
      <div class="card">
        <div class="card-title">&#x1F532; CPU</div>
        <div class="card-value" id="cpu-value">--</div>
        <div class="card-detail">all cores</div>
        <div class="progress-bar">
          <div class="progress-fill" id="cpu-bar" style="width: 0%"></div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">&#x1F9E0; Memory</div>
        <div class="card-value" id="mem-value">--</div>
        <div class="card-detail" id="mem-detail">-- / -- MB</div>
        <div class="progress-bar">
          <div class="progress-fill" id="mem-bar" style="width: 0%"></div>
        </div>
      </div>
    </div>

    <div class="info-row">
      <span class="info-label">&#x23F1;&#xFE0F; Uptime</span>
      <span class="info-value" id="uptime-value">--</span>
    </div>
    <div class="info-row">
      <span class="info-label">&#x1F3F7;&#xFE0F; Hostname</span>
      <span class="info-value" id="hostname-value">--</span>
    </div>
    <div class="status-bar" id="status-bar">&#x5F85;&#x673A;&#x4E2D;...</div>
  </div>

  <script>
    /**
     * 前端逻辑: 每 5 秒从 /api/status 获取数据并更新 DOM。
     *
     * 关键 API:
     *   fetch()  — 浏览器原生 HTTP 请求（无需 jQuery/axios）
     *   setInterval() — 定时刷新
     *   document.getElementById().textContent — 更新页面内容
     */

    // 根据百分比返回 CSS 类名: <50% 绿色, 50-80% 橙色, >80% 红色
    function progressClass(pct) {
      if (pct < 50) return 'low';
      if (pct < 80) return 'medium';
      return 'high';
    }

    // 将秒数格式化为 "3d 2h 15m" 格式
    function formatUptime(seconds) {
      var d = Math.floor(seconds / 86400);
      var h = Math.floor((seconds % 86400) / 3600);
      var m = Math.floor((seconds % 3600) / 60);
      var parts = [];
      if (d > 0) parts.push(d + 'd');
      if (h > 0) parts.push(h + 'h');
      if (m > 0) parts.push(m + 'm');
      return parts.length > 0 ? parts.join(' ') : '< 1m';
    }

    // 核心: 获取数据并更新页面
    async function update() {
      var bar = document.getElementById('status-bar');

      try {
        var res = await fetch('/api/status');
        var data = await res.json();

        if (data.error) throw new Error(data.error);

        // --- CPU ---
        document.getElementById('cpu-value').textContent = data.cpu + '%';
        var cpuBar = document.getElementById('cpu-bar');
        cpuBar.style.width = data.cpu + '%';
        cpuBar.className = 'progress-fill ' + progressClass(data.cpu);

        // --- 内存 ---
        var memPct = Math.round(data.memory.used / data.memory.total * 100);
        document.getElementById('mem-value').textContent = memPct + '%';
        document.getElementById('mem-detail').textContent =
          data.memory.used + ' / ' + data.memory.total + ' MB';
        var memBar = document.getElementById('mem-bar');
        memBar.style.width = memPct + '%';
        memBar.className = 'progress-fill ' + progressClass(memPct);

        // --- 磁盘卡片（动态生成，支持多个分区） ---
        renderDiskCards(data.disks);

        // --- Uptime & Hostname ---
        document.getElementById('uptime-value').textContent = formatUptime(data.uptime);
        document.getElementById('hostname-value').textContent = data.hostname;
        document.getElementById('hostname-display').textContent = data.hostname + '.local';

        bar.textContent = '\\u5237\\u65b0\\u95f4\\u9694 5s \\u00b7 \\u72b6\\u6001\\u6b63\\u5e38';
        bar.className = 'status-bar';
      } catch (err) {
        bar.textContent = '\\u26a0\\ufe0f \\u8fde\\u63a5\\u5931\\u8d25\\uff0c\\u5c06\\u5728 5 \\u79d2\\u540e\\u91cd\\u8bd5';
        bar.className = 'status-bar error';
      }
    }

    // 动态渲染磁盘卡片
    function renderDiskCards(disks) {
      var container = document.getElementById('cards-container');

      // 移除旧的磁盘卡片（保留 CPU 和 Memory 卡片）
      var oldDiskCards = container.querySelectorAll('.disk-card');
      for (var i = 0; i < oldDiskCards.length; i++) {
        oldDiskCards[i].remove();
      }

      // 为每个磁盘分区创建卡片
      for (var i = 0; i < disks.length; i++) {
        var disk = disks[i];
        var card = document.createElement('div');
        card.className = 'card disk-card';
        card.innerHTML =
          '<div class="card-title">&#x1F4BE; Disk (' + disk.mount + ')</div>' +
          '<div class="card-value">' + disk.percent + '%</div>' +
          '<div class="card-detail">' + disk.used + ' / ' + disk.total + '</div>' +
          '<div class="progress-bar">' +
            '<div class="progress-fill ' + progressClass(disk.percent) +
            '" style="width:' + disk.percent + '%"></div>' +
          '</div>';
        container.appendChild(card);
      }
    }

    // 页面加载后立即获取一次数据，然后每 5 秒刷新
    update();
    setInterval(update, 5000);
  </script>
</body>
</html>`);
});
```

- [ ] **Step 3: Start server and test the full flow**

Run: `node server.js`
Expected: Server starts, banner printed.

Test API in another terminal:
```
curl -s http://localhost:3000/api/status | python3 -m json.tool
```
Expected: JSON with `cpu`, `memory`, `disks`, `uptime`, `hostname` fields. `disks` should be an array with 1–2 entries.

Test HTML page:
```
curl -s http://localhost:3000/ | head -5
```
Expected: `<!DOCTYPE html>` ...

Stop the server (Ctrl+C) after verifying.

- [ ] **Step 4: Commit**

```bash
git add server.js
git commit -m "feat: add /api/status route and embedded dashboard HTML"
```

---

### Task 5: README.md documentation

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: nothing (standalone doc)
- Produces: README.md covering 功能、安装、启动、访问方式、已知限制

- [ ] **Step 1: Write README.md**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with install, startup, and access instructions"
```

---

### Task 6: DevLog — 开发过程记录

**Files:**
- Create: `DevLog/2026-07-06.md`

**Interfaces:**
- Consumes: nothing (standalone record)
- Produces: DevLog entry for this session

- [ ] **Step 1: Create DevLog directory and write log**

```bash
mkdir -p DevLog
```

Write `DevLog/2026-07-06.md`:

```markdown
# DevLog — 2026-07-06

## 第 1 轮

**用户 Prompt:**
我们正在 Arduino UNO-Q 开发板的 Linux 侧进行 AI Vibe Coding Workshop。
请你帮助我开发一个简单的本地 Web App，用于展示 UNO-Q 当前的系统状态...
（完整 Prompt 见对话开头，包含功能需求、技术约束、开发范围）

**AI Agent 主要行动:**
1. 探索项目上下文：检查目录结构（空仓库）、Git 历史、Node.js/npm 版本（v24.18.0）、系统架构（aarch64）
2. 询问项目结构偏好：单文件 vs 分离前后端 vs 零依赖 → 用户选择单文件方案（A）
3. 询问端口号 → 用户选择 3000（A）
4. 呈现完整设计方案：架构图、技术选型表、页面布局、API 设计、数据流、错误处理
5. 用户反馈：刷新间隔改为 5 秒（原 2 秒）
6. 用户补充：需监听 0.0.0.0、代码结构需适合教学
7. 用户补充：磁盘需同时显示 `/` 和 `/home` 两个分区；DevLog 使用文件夹而非单文件
8. 更新设计文档，将 disk 改为 disks 数组，布局从 3 列改为 4 列（动态生成磁盘卡片）
9. 提交设计文档到 `docs/superpowers/specs/2026-07-06-unoq-status-web-design.md`
10. 编写实施计划（本文件）

**最终回复摘要:**
设计完成并确认。项目采用单文件 server.js（~180 行含注释），Express 监听 0.0.0.0:3000。
前端使用原生 fetch() + setInterval(5000) 自动刷新，磁盘卡片动态生成支持多分区。
唯一依赖：express。已进入实施计划编写阶段。
```

- [ ] **Step 2: Commit**

```bash
git add DevLog/2026-07-06.md
git commit -m "docs: add DevLog entry for 2026-07-06"
```

---

### Task 7: Final startup and end-to-end verification

**Files:**
- No files created or modified

**Interfaces:**
- Consumes: Complete `server.js` (all prior tasks)
- Produces: Verified running application

- [ ] **Step 1: Start the server in background and test API**

```bash
node server.js &
SERVER_PID=$!
sleep 2
```

Run: `curl -s http://localhost:3000/api/status | python3 -m json.tool`

Expected output structure:
```json
{
    "cpu": <number>,
    "memory": {
        "used": <number>,
        "total": <number>,
        "unit": "MB"
    },
    "disks": [
        {
            "mount": "/",
            "total": "<string>",
            "used": "<string>",
            "percent": <number>
        },
        {
            "mount": "/home",
            "total": "<string>",
            "used": "<string>",
            "percent": <number>
        }
    ],
    "uptime": <number>,
    "hostname": "<string>"
}
```

- [ ] **Step 2: Verify HTML page is served**

Run: `curl -s http://localhost:3000/ | grep -c 'UNO-Q System Status'`
Expected: `1` (title appears in HTML)

- [ ] **Step 3: Verify 0.0.0.0 binding**

Run: `ss -tlnp | grep 3000`
Expected: output contains `0.0.0.0:3000` or `*:3000`

- [ ] **Step 4: Verify all fields are non-empty**

Run:
```bash
curl -s http://localhost:3000/api/status | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert isinstance(d['cpu'], (int, float)), 'cpu missing'
assert d['memory']['used'] > 0, 'memory.used missing'
assert len(d['disks']) >= 1, 'disks empty'
assert d['uptime'] > 0, 'uptime missing'
assert len(d['hostname']) > 0, 'hostname missing'
print('All checks passed!')
"
```
Expected: `All checks passed!`

- [ ] **Step 5: Stop the server**

```bash
kill $SERVER_PID
```

- [ ] **Step 6: Final commit (if any changes from verification fixes)**

```bash
git status
# Only commit if verification revealed issues that needed fixing
```
