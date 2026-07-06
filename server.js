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

const { execSync } = require('child_process');

/**
 * 获取本机局域网 IPv4 地址
 *
 * 遍历所有网络接口，跳过：
 *   - 内部回环接口 (lo)
 *   - Docker 虚拟网桥 (docker*)
 * 返回找到的第一个非内部 IPv4 地址
 */
function getLanIP() {
  const interfaces = os.networkInterfaces();
  for (const name of Object.keys(interfaces)) {
    // 跳过回环和 Docker 虚拟接口
    if (name === 'lo' || name.startsWith('docker')) continue;
    for (const iface of interfaces[name]) {
      // 只取 IPv4，跳过内部地址 (127.x.x.x)
      if (iface.family === 'IPv4' && !iface.internal) {
        return iface.address;
      }
    }
  }
  return '无法获取'; // fallback
}

// ============================================================
// 数据采集函数
// ============================================================

/**
 * 获取 CPU 使用率（百分比）
 *
 * 原理: CPU 使用率是瞬时值，无法直接读取一个"当前使用率"的数字。
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

// ============================================================
// 启动服务器 — 关键: 显式绑定 0.0.0.0
// 如果省略 host 参数，Express 默认只监听 127.0.0.1（本机回环），
// 局域网内其他设备将无法访问。
// 0.0.0.0 表示"监听本机所有网络接口"，包括 WiFi 和以太网。
// ============================================================
const server = app.listen(PORT, '0.0.0.0', () => {
  const ip = getLanIP();
  console.log('============================================');
  console.log('  UNO-Q Status Web 已启动');
  console.log(`  本地访问:     http://localhost:${PORT}`);
  console.log(`  局域网访问:   http://${ip}:${PORT}`);
  console.log(`  主机名访问:   http://${os.hostname()}.local:${PORT}`);
  console.log('============================================');
});

// 优雅处理端口占用等启动错误
server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    console.error('============================================');
    console.error('  ⚠️  端口已被占用！');
    console.error(`  端口 ${PORT} 上已有其他程序在运行。`);
    console.error(`  请先关闭占用端口的进程:`);
    console.error(`    fuser -k ${PORT}/tcp`);
    console.error(`  然后重新运行: npm start`);
    console.error('============================================');
  } else {
    console.error('启动失败:', err.message);
  }
  process.exit(1);
});
