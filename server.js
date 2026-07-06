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
// 0.0.0.0 表示"监听本机所有网络接口"，包括 WiFi 和以太网。
// ============================================================
app.listen(PORT, '0.0.0.0', () => {
  console.log('============================================');
  console.log('  UNO-Q Status Web 已启动');
  console.log(`  本地访问:     http://localhost:${PORT}`);
  console.log(`  局域网访问:   http://${os.hostname()}.local:${PORT}`);
  console.log(`  IP 访问:      http://<board-ip>:${PORT}`);
  console.log('============================================');
});
