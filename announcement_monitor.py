#!/usr/bin/env python3
"""每天 9 点抓取中科星图与特变电工公告，并调用千问 codinplan 分析。"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib import error, parse, request


EASTMONEY_API = "https://np-anotice-stock.eastmoney.com/api/security/ann"
QWEN_API = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_MODEL = "qwen-codinplan"
DEFAULT_DB = "announcements.db"


@dataclass(frozen=True)
class Company:
    name: str
    code: str


COMPANIES = [
    Company(name="中科星图", code="688568"),
    Company(name="特变电工", code="600089"),
]


def http_get_json(url: str, params: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    full_url = f"{url}?{parse.urlencode(params)}"
    req = request.Request(full_url, method="GET")
    with request.urlopen(req, timeout=timeout) as resp:
        content = resp.read().decode("utf-8")
    return json.loads(content)


def http_post_json(
    url: str, headers: dict[str, str], body: dict[str, Any], timeout: int = 60
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = request.Request(url, data=data, headers=headers, method="POST")
    with request.urlopen(req, timeout=timeout) as resp:
        content = resp.read().decode("utf-8")
    return json.loads(content)


def init_db(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS announcements (
                art_code TEXT PRIMARY KEY,
                company TEXT NOT NULL,
                title TEXT NOT NULL,
                notice_date TEXT NOT NULL,
                url TEXT,
                analysis TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def is_seen(db_path: str, art_code: str) -> bool:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM announcements WHERE art_code = ?", (art_code,)
        ).fetchone()
    return row is not None


def save_announcement(
    db_path: str,
    art_code: str,
    company: str,
    title: str,
    notice_date: str,
    url: str,
    analysis: str,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO announcements
            (art_code, company, title, notice_date, url, analysis, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                art_code,
                company,
                title,
                notice_date,
                url,
                analysis,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()


def fetch_announcements(company: Company, page_size: int = 30) -> list[dict[str, Any]]:
    params = {
        "sr": -1,
        "page_size": page_size,
        "page_index": 1,
        "ann_type": "A",
        "client_source": "web",
        "stock_list": company.code,
    }
    payload = http_get_json(EASTMONEY_API, params)
    if payload.get("success") != 1:
        raise RuntimeError(f"东方财富接口返回异常: {payload}")

    return payload.get("data", {}).get("list", [])


def build_announcement_url(art_code: str) -> str:
    return f"https://data.eastmoney.com/notices/detail/{art_code}.html"


def analyze_with_qwen(
    api_key: str,
    model: str,
    company: str,
    title: str,
    notice_date: str,
    url: str,
) -> str:
    prompt = (
        "你是一名A股公告分析师，请基于下面信息输出结构化分析：\n"
        "1) 公告类型判断\n"
        "2) 对公司基本面的潜在影响（短期/中长期）\n"
        "3) 对投资者关注点的提示\n"
        "4) 一句话结论（偏利好/中性/偏利空）\n\n"
        f"公司：{company}\n标题：{title}\n公告日期：{notice_date}\n链接：{url}\n"
    )
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是严谨的金融公告研究助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    payload = http_post_json(QWEN_API, headers=headers, body=body)
    choices = payload.get("choices", [])
    if not choices:
        raise RuntimeError(f"千问接口返回异常: {payload}")

    return choices[0]["message"]["content"].strip()


def process_once(db_path: str, qwen_api_key: str, qwen_model: str, page_size: int) -> None:
    logging.info("开始抓取公告。")
    new_count = 0

    for company in COMPANIES:
        logging.info("抓取 %s(%s) 公告。", company.name, company.code)
        announcements = fetch_announcements(company, page_size=page_size)

        for ann in announcements:
            art_code = ann.get("art_code")
            if not art_code or is_seen(db_path, art_code):
                continue

            title = ann.get("title", "(无标题)")
            notice_date = ann.get("notice_date", "")
            url = ann.get("art_url") or build_announcement_url(art_code)

            logging.info("发现新公告：%s - %s", company.name, title)
            analysis = analyze_with_qwen(
                api_key=qwen_api_key,
                model=qwen_model,
                company=company.name,
                title=title,
                notice_date=notice_date,
                url=url,
            )
            save_announcement(
                db_path=db_path,
                art_code=art_code,
                company=company.name,
                title=title,
                notice_date=notice_date,
                url=url,
                analysis=analysis,
            )
            new_count += 1
            logging.info("公告已分析并入库：%s", art_code)

    logging.info("本次执行完成，新公告数量：%s", new_count)


def seconds_until_next_9am() -> float:
    now = datetime.now()
    next_run = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if now >= next_run:
        next_run += timedelta(days=1)
    return (next_run - now).total_seconds()


def run_daily(db_path: str, qwen_api_key: str, qwen_model: str, page_size: int) -> None:
    logging.info("调度器已启动，将在每天 09:00 执行。")
    while True:
        wait_seconds = seconds_until_next_9am()
        logging.info("距离下一次执行还有 %.0f 秒。", wait_seconds)
        time.sleep(wait_seconds)

        try:
            process_once(db_path, qwen_api_key, qwen_model, page_size)
        except Exception as exc:  # noqa: BLE001
            logging.exception("定时任务执行失败: %s", exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="每天 9 点抓取中科星图与特变电工公告并调用千问分析"
    )
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite 数据库路径")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="千问模型名，默认 qwen-codinplan")
    parser.add_argument("--page-size", type=int, default=30, help="每只股票每次抓取公告条数")
    parser.add_argument("--run-once", action="store_true", help="立即执行一次并退出")
    parser.add_argument("--log-level", default="INFO", help="日志等级，例如 INFO/DEBUG")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    qwen_api_key = os.getenv("DASHSCOPE_API_KEY")
    if not qwen_api_key:
        raise RuntimeError("请先设置环境变量 DASHSCOPE_API_KEY")

    init_db(args.db)

    if args.run_once:
        process_once(args.db, qwen_api_key, args.model, args.page_size)
    else:
        run_daily(args.db, qwen_api_key, args.model, args.page_size)


if __name__ == "__main__":
    try:
        main()
    except error.HTTPError as exc:
        logging.error("HTTP请求失败: %s %s", exc.code, exc.reason)
        raise
