# 保活任务系统

## 概述
双守护保活系统，每小时自动检查 scanner.py 和 web_log_viewer.py 的运行状态，未运行则自动重启，并报告最新速度指标。

## 文件结构

```
/workspace/
├── keepalive.sh              # 主保活脚本(核心逻辑)
├── start_keepalive.sh        # 启动守护进程
├── stop_keepalive.sh         # 停止守护进程
├── check_keepalive.sh        # 手动触发一次检查
├── scanner.py                # 多链私钥扫描器(需要提供)
├── web_log_viewer.py         # Web日志查看器(需要提供)
├── run.sh                    # scanner启动脚本(需要提供)
├── start_viewer.sh           # viewer启动脚本(需要提供)
├── .scanner.pid              # scanner进程ID文件(自动生成)
├── .viewer.pid               # viewer进程ID文件(自动生成)
└── output/
    ├── found_wallets.jsonl   # 命中的钱包记录
    ├── stats.json            # 速度指标和统计
    ├── scanner.log           # scanner日志
    ├── viewer.log            # viewer日志
    └── keepalive_failures    # 连续失败计数器
```

## 使用方法

### 1. 启动守护进程(推荐)
```bash
cd /workspace
bash start_keepalive.sh
```
守护进程会每小时自动执行一次保活检查。

### 2. 手动触发检查
```bash
cd /workspace
bash check_keepalive.sh
```

### 3. 停止守护进程
```bash
cd /workspace
bash stop_keepalive.sh
```

## 核心功能

### Scanner 监控
- 读取 `.scanner.pid` 获取进程ID
- 使用 `ps -p <PID>` 检查进程存活
- 若不存活: 执行 `SCAN_INTERVAL=0.3 bash run.sh` 重启
- 等待10秒让benchmark完成

### Viewer 监控
- 读取 `.viewer.pid` 获取进程ID
- 使用 `ps -p <PID>` 检查进程存活
- 使用 `curl` 验证HTTP服务(返回200)
- 若不存活: 执行 `PORT=8080 bash start_viewer.sh` 重启
- 等待2秒确认服务启动

### 速度指标报告
从 `output/stats.json` 读取并显示:
- 扫描速度(全程): addr/s
- 扫描速度(近30): addr/s
- 计算速度: keys/s
- 累计扫描、命中、运行时间

### 连续失败处理
- 失败计数器: `output/keepalive_failures`
- 任一服务失败则 +1
- 都成功则清零
- ≥3次时输出警告并显示日志末尾

## 输出格式示例

```
========================================
保活任务检查 - 2026-08-04 10:00:00
========================================

scanner: 运行中 PID=12345 已运行=05:23:15
viewer: 运行中 PID=12346 已运行=05:23:14 访问 http://192.168.1.100:8080/

速度指标:
  扫描速度(全程)=125.5 addr/s
  扫描速度(近30)=130.2 addr/s
  计算速度=150.8 keys/s

累计统计:
  累计扫描=500000
  命中=23
  本次运行=19815s

========================================
保活检查完成
========================================
```

## 注意事项

1. **不要修改核心文件**
   - scanner.py, web_log_viewer.py, run.sh, start_viewer.sh 的逻辑不应修改
   - 不要删除 output/ 下的任何文件

2. **进程管理**
   - 仅在进程不存活时才重启
   - 存活时不会重复启动(避免多开)

3. **日志文件**
   - keepalive.log: 保活任务执行日志
   - scanner.log: scanner运行日志
   - viewer.log: viewer运行日志

4. **依赖检查**
   - 需要 `jq` 命令解析JSON(可选)
   - 如果没有jq，会显示原始JSON

## 部署前准备

确保以下文件已存在并可正常工作:
1. `/workspace/scanner.py` - 多链私钥扫描器
2. `/workspace/web_log_viewer.py` - Web日志查看器
3. `/workspace/run.sh` - scanner启动脚本(会生成 .scanner.pid)
4. `/workspace/start_viewer.sh` - viewer启动脚本(会生成 .viewer.pid)

启动脚本要求:
- `run.sh`: 启动scanner并写入进程ID到 `.scanner.pid`
- `start_viewer.sh`: 启动viewer并写入进程ID到 `.viewer.pid`

## 定时任务(可选)

如果不想使用守护进程，可以使用 crontab:
```bash
# 编辑定时任务
crontab -e

# 添加以下行(每小时执行一次)
0 * * * * /bin/bash /workspace/keepalive.sh >> /workspace/output/keepalive.log 2>&1
```