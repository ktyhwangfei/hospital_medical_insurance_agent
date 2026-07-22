import os
import re
import json
import time
import sqlite3
import requests
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime

COLUMNS = [
    {
        "name": "政策文件",
        # "base_url": "https://ybj.beijing.gov.cn/zwgk/2024zcwj/"
        "base_url": "https://ybj.beijing.gov.cn/zwgk/2020_zfxxgk/2020_xxgkml/202501/t20250120_3994118.html"
    }
]

SAVE_DIR = "./raw"
ATTACH_DIR = os.path.join(SAVE_DIR, "attachments")
DB_PATH = os.path.join(SAVE_DIR, "ybj_policy_crawler.db")
EXCEL_PATH = os.path.join(SAVE_DIR, "北京市医保局政策文件2.xlsx")

os.makedirs(ATTACH_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 Chrome/120 Safari/537.36"
}

ATTACH_EXTS = [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".txt", ".ofd"]

EXPORT_FIELDS = [
    "主题分类",
    "标题",
    "发布日期",
    "废止日期",
    "有效性",
    "成文日期",
    "实施日期",
    "发文机构",
    "发文字号",
    "文件来源",
    "详情页URL",
    "正文内容",
    "附件名称",
    "附件URL",
    "附件本地路径",
    "爬取时间",
    "爬取状态",
    "内容大小"
]


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean_filename(name: str) -> str:
    name = name or "未命名附件"
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name.strip()[:150]


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        detail_url TEXT UNIQUE,
        title TEXT,
        publish_date TEXT,
        crawl_status TEXT DEFAULT 'pending',
        data_json TEXT,
        error_msg TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    conn.commit()
    conn.close()


def get_conn():
    return sqlite3.connect(DB_PATH)


def request_url(url, timeout=20):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.encoding = resp.apparent_encoding
        time.sleep(1)
        return resp
    except Exception as e:
        print(f"请求异常：{url}，错误：{e}")
        return None


def guess_list_pages(base_url, max_pages=50):
    urls = [base_url]
    for i in range(1, max_pages):
        urls.append(urljoin(base_url, f"index_{i}.html"))
    return urls


def parse_list_page(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for a in soup.find_all("a"):
        title = a.get_text(strip=True)
        href = a.get("href")

        if not title or not href:
            continue

        full_url = urljoin(page_url, href)

        if not full_url.endswith(".html"):
            continue

        if "/zwgk/" not in full_url:
            continue

        if len(title) < 8:
            continue

        if title in ["首页", "政策文件", "政策解读", "政务公开"]:
            continue

        parent_text = a.parent.get_text(" ", strip=True) if a.parent else ""
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", parent_text)
        pub_date = date_match.group(0) if date_match else ""

        results.append({
            "标题": title,
            "发布日期": pub_date,
            "详情页URL": full_url
        })

    dedup = {}
    for item in results:
        dedup[item["详情页URL"]] = item

    return list(dedup.values())


def save_list_items(items):
    conn = get_conn()
    cur = conn.cursor()

    inserted = 0
    for item in items:
        cur.execute("""
        INSERT OR IGNORE INTO policies
        (detail_url, title, publish_date, crawl_status, created_at, updated_at)
        VALUES (?, ?, ?, 'pending', ?, ?)
        """, (
            item["详情页URL"],
            item["标题"],
            item["发布日期"],
            now_str(),
            now_str()
        ))

        if cur.rowcount > 0:
            inserted += 1

    conn.commit()
    conn.close()
    return inserted


def crawl_list_pages():
    for column in COLUMNS:
        base_url = column["base_url"]
        empty_count = 0

        for page_url in guess_list_pages(base_url):
            print(f"正在抓取列表页：{page_url}")
            resp = request_url(page_url)

            if not resp:
                empty_count += 1
                continue

            if resp.status_code == 404:
                print(f"列表页不存在：{page_url}")
                empty_count += 1
                if empty_count >= 3:
                    break
                continue

            if resp.status_code != 200:
                print(f"请求失败：{page_url}，状态码：{resp.status_code}")
                empty_count += 1
                continue

            items = parse_list_page(resp.text, page_url)

            if not items:
                print(f"未发现数据：{page_url}")
                empty_count += 1
                if empty_count >= 3:
                    break
                continue

            empty_count = 0
            inserted = save_list_items(items)
            print(f"发现 {len(items)} 条，新增 {inserted} 条")


def extract_meta(soup):
    text = soup.get_text("\n", strip=True)

    meta = {
        "主题分类": "",
        "发布日期": "",
        "废止日期": "",
        "有效性": "",
        "成文日期": "",
        "实施日期": "",
        "发文机构": "",
        "发文字号": "",
        "文件来源": ""
    }

    for key in meta:
        patterns = [
            rf"\[{key}\]\s*([^\n]+)",
            rf"{key}[:：]\s*([^\n]+)"
        ]

        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                meta[key] = m.group(1).strip()
                break

    return meta


def extract_title(soup):
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)

    title = soup.find("title")
    if title:
        return title.get_text(strip=True).split("_")[0]

    return ""


def extract_content(soup):
    candidates = [
        soup.find("div", class_=re.compile("TRS_Editor|content|article|main|detail", re.I)),
        soup.find("div", id=re.compile("TRS_Editor|content|article|main|detail", re.I)),
        soup.find("body")
    ]

    content = ""
    for node in candidates:
        if node:
            text = node.get_text("\n", strip=True)
            if len(text) > len(content):
                content = text

    return content.strip()


def download_attachment(file_url, name=""):
    filename = clean_filename(name or os.path.basename(urlparse(file_url).path))
    ext = os.path.splitext(urlparse(file_url).path)[1]

    if ext and not filename.lower().endswith(ext.lower()):
        filename += ext

    local_path = os.path.join(ATTACH_DIR, filename)

    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return local_path

    resp = request_url(file_url, timeout=60)

    if resp and resp.status_code == 200:
        with open(local_path, "wb") as f:
            f.write(resp.content)
        print(f"附件已下载：{local_path}")
        return local_path

    return ""


def extract_attachments(soup, detail_url):
    attachments = []

    for a in soup.find_all("a"):
        href = a.get("href")
        name = a.get_text(strip=True)

        if not href:
            continue

        full_url = urljoin(detail_url, href)
        path = urlparse(full_url).path.lower()

        if any(path.endswith(ext) for ext in ATTACH_EXTS):
            local_path = download_attachment(full_url, name)
            attachments.append({
                "附件名称": name or os.path.basename(path),
                "附件URL": full_url,
                "附件本地路径": local_path
            })

    return attachments


def parse_detail_page(detail_url):
    resp = request_url(detail_url)

    if not resp:
        raise Exception("详情页请求异常")

    if resp.status_code != 200:
        raise Exception(f"详情页状态码异常：{resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")

    meta = extract_meta(soup)
    title = extract_title(soup)
    content = extract_content(soup)
    attachments = extract_attachments(soup, detail_url)

    base_row = {
        "主题分类": meta.get("主题分类", ""),
        "标题": title,
        "发布日期": meta.get("发布日期", ""),
        "废止日期": meta.get("废止日期", ""),
        "有效性": meta.get("有效性", ""),
        "成文日期": meta.get("成文日期", ""),
        "实施日期": meta.get("实施日期", ""),
        "发文机构": meta.get("发文机构", ""),
        "发文字号": meta.get("发文字号", ""),
        "文件来源": meta.get("文件来源", ""),
        "详情页URL": detail_url,
        "正文内容": content,
        "爬取时间": now_str(),
        "爬取状态": "done",
        "内容大小": len(content)
    }

    if not attachments:
        return [{
            **base_row,
            "附件名称": "",
            "附件URL": "",
            "附件本地路径": ""
        }]

    rows = []
    for att in attachments:
        rows.append({
            **base_row,
            "附件名称": att.get("附件名称", ""),
            "附件URL": att.get("附件URL", ""),
            "附件本地路径": att.get("附件本地路径", "")
        })

    return rows


def get_pending_policies():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, detail_url, title
    FROM policies
    WHERE crawl_status IN ('pending', 'failed')
    ORDER BY id ASC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def update_success(policy_id, data_rows):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    UPDATE policies
    SET crawl_status = 'done',
        data_json = ?,
        error_msg = NULL,
        updated_at = ?
    WHERE id = ?
    """, (
        json.dumps(data_rows, ensure_ascii=False),
        now_str(),
        policy_id
    ))

    conn.commit()
    conn.close()


def update_failed(policy_id, error_msg):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    UPDATE policies
    SET crawl_status = 'failed',
        error_msg = ?,
        updated_at = ?
    WHERE id = ?
    """, (
        error_msg,
        now_str(),
        policy_id
    ))

    conn.commit()
    conn.close()


def crawl_detail_pages():
    rows = get_pending_policies()
    print(f"待抓取详情页数量：{len(rows)}")

    for policy_id, detail_url, title in rows:
        print(f"正在抓取详情页：{title}")

        try:
            data_rows = parse_detail_page(detail_url)
            update_success(policy_id, data_rows)
            print(f"完成：{title}")

        except Exception as e:
            update_failed(policy_id, str(e))
            print(f"失败：{title}，原因：{e}")


def export_excel():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT data_json, detail_url, title, publish_date, crawl_status, error_msg, updated_at
    FROM policies
    ORDER BY id ASC
    """)

    all_rows = []

    for data_json, detail_url, title, publish_date, crawl_status, error_msg, updated_at in cur.fetchall():
        if data_json:
            try:
                rows = json.loads(data_json)
                all_rows.extend(rows)
                continue
            except Exception:
                pass

        all_rows.append({
            "主题分类": "",
            "标题": title or "",
            "发布日期": publish_date or "",
            "废止日期": "",
            "有效性": "",
            "成文日期": "",
            "实施日期": "",
            "发文机构": "",
            "发文字号": "",
            "文件来源": "",
            "详情页URL": detail_url or "",
            "正文内容": "",
            "附件名称": "",
            "附件URL": "",
            "附件本地路径": "",
            "爬取时间": updated_at or "",
            "爬取状态": crawl_status or "",
            "内容大小": 0
        })

    conn.close()

    df = pd.DataFrame(all_rows)

    for field in EXPORT_FIELDS:
        if field not in df.columns:
            df[field] = ""

    df = df[EXPORT_FIELDS]
    df.to_excel(EXCEL_PATH, index=False)

    print(f"Excel 已导出：{EXCEL_PATH}")
    print(f"总行数：{len(df)}")


def main():
    init_db()

    print("第一步：扫描列表页")
    crawl_list_pages()

    print("第二步：抓取详情页")
    crawl_detail_pages()

    print("第三步：导出 Excel")
    export_excel()

    print("全部完成")


if __name__ == "__main__":
    main()