# 公告自动抓取与千问分析

该程序会每天 **09:00（Asia/Shanghai）** 自动抓取以下上市公司最新公告，并将“新公告”交给千问 `qwen-codinplan` 模型分析：

- 中科星图（`688568`）
- 特变电工（`600089`）

程序会把公告和分析结果保存到本地 SQLite 数据库，避免重复分析同一条公告。

## 1. 安装依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 配置千问 API Key

```bash
export DASHSCOPE_API_KEY="你的DashScope API Key"
```

## 3. 立即运行一次（调试推荐）

```bash
python announcement_monitor.py --run-once
```

## 4. 常驻运行（每天9点执行）

```bash
python announcement_monitor.py
```

## 5. 常用参数

- `--db`: SQLite 数据库文件路径（默认 `announcements.db`）
- `--model`: 千问模型名（默认 `qwen-codinplan`）
- `--page-size`: 每只股票单次拉取公告数（默认 `30`）
- `--log-level`: 日志级别，例如 `INFO` 或 `DEBUG`

示例：

```bash
python announcement_monitor.py --db data/ann.db --model qwen-codinplan --page-size 50 --log-level DEBUG
```

## 6. 数据库结构

表名：`announcements`

- `art_code`: 公告唯一ID（主键）
- `company`: 公司名称
- `title`: 公告标题
- `notice_date`: 公告发布时间
- `url`: 公告链接
- `analysis`: 千问分析内容
- `created_at`: 入库时间

## 7. 说明

- 公告源接口使用东方财富公告 API。
- 如需扩展公司，只需在 `announcement_monitor.py` 的 `COMPANIES` 列表中新增股票代码。
