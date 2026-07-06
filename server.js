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
