import os
import re
import json
import time
import sqlite3
import hashlib
import requests
import pandas as pd

from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin, urlparse, unquote


# BASE_URL = "https://www.beijing.gov.cn/zhengce/zhengcefagui/"
BASE_URL = "https://ybj.beijing.gov.cn/zwgk/2020_zfxxgk/2020_xxgkml/202501/t20250120_3994118.html"
RAW_DIR = "./raw"
ATTACH_DIR = "./raw/attachments"
DB_PATH = "./raw/beijing_gov_policy_crawler.db"
EXCEL_PATH = "./raw/北京市政策法规文件3.xlsx"

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(ATTACH_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}

ATTACH_EXTS = [
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".zip", ".rar", ".txt", ".wps", ".ofd"
]


FIELDS = [
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
    "内容大小",
]


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean_filename(name: str) -> str:
    if not name:
        name = "未命名文件"
    name = unquote(name)
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180]


def md5_text(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        detail_url TEXT UNIQUE,
        title TEXT,
        publish_date TEXT,
        valid_status TEXT,
        crawl_status TEXT DEFAULT 'pending',
        error_msg TEXT,
        data_json TEXT,
        created_at TEXT,
        updated_at TEXT
    )
    """)

    conn.commit()
    conn.close()


def get_conn():
    return sqlite3.connect(DB_PATH)


def request_url(url: str, timeout=25):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.encoding = resp.apparent_encoding
        time.sleep(1)
        return resp
    except Exception as e:
        print(f"请求异常：{url}，原因：{e}")
        return None


def parse_list_page(html: str, page_url: str):
    """
    首都之窗政策文件页面列表结构大致为：
    有效性 + 标题链接 + 发布日期
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []

    for a in soup.find_all("a"):
        title = a.get_text(strip=True)
        href = a.get("href")

        if not href or not title:
            continue

        detail_url = urljoin(page_url, href)

        if "/zhengce/zhengcefagui/" not in detail_url:
            continue

        if not detail_url.endswith(".html"):
            continue

        if len(title) < 6:
            continue

        parent_text = a.parent.get_text(" ", strip=True) if a.parent else ""
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", parent_text)
        publish_date = date_match.group(0) if date_match else ""

        valid_status = ""
        if parent_text.startswith("是"):
            valid_status = "是"
        elif parent_text.startswith("否"):
            valid_status = "否"

        items.append({
            "title": title,
            "publish_date": publish_date,
            "valid_status": valid_status,
            "detail_url": detail_url
        })

    # 去重
    dedup = {}
    for item in items:
        dedup[item["detail_url"]] = item

    return list(dedup.values())


def save_list_items(items):
    conn = get_conn()
    cur = conn.cursor()

    inserted = 0
    for item in items:
        try:
            cur.execute("""
            INSERT OR IGNORE INTO policies
            (
                detail_url,
                title,
                publish_date,
                valid_status,
                crawl_status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, 'pending', ?, ?)
            """, (
                item["detail_url"],
                item["title"],
                item["publish_date"],
                item["valid_status"],
                now_str(),
                now_str()
            ))

            if cur.rowcount > 0:
                inserted += 1

        except Exception as e:
            print(f"保存列表项失败：{item['detail_url']}，原因：{e}")

    conn.commit()
    conn.close()
    return inserted


def get_list_urls(max_pages=200):
    """
    兼容常见分页：
    - 首页：BASE_URL
    - index.html
    - index_1.html
    - index_2.html

    如果该栏目本身一次性加载大量数据，后续分页会自动404/空列表停止。
    """
    urls = [BASE_URL, urljoin(BASE_URL, "index.html")]
    for i in range(1, max_pages):
        urls.append(urljoin(BASE_URL, f"index_{i}.html"))
    return urls


def crawl_list_pages():
    empty_or_404_count = 0

    for page_url in get_list_urls():
        print(f"正在抓取列表页：{page_url}")
        resp = request_url(page_url)

        if resp is None:
            empty_or_404_count += 1
            continue

        if resp.status_code == 404:
            print(f"列表页不存在：{page_url}")
            empty_or_404_count += 1
            if empty_or_404_count >= 3:
                print("连续多个分页不存在，停止列表页扫描。")
                break
            continue

        if resp.status_code != 200:
            print(f"列表页请求失败：{page_url}，状态码：{resp.status_code}")
            empty_or_404_count += 1
            continue

        items = parse_list_page(resp.text, page_url)

        if not items:
            print(f"列表页无有效数据：{page_url}")
            empty_or_404_count += 1
            if empty_or_404_count >= 3:
                print("连续多个空列表，停止列表页扫描。")
                break
            continue

        empty_or_404_count = 0
        inserted = save_list_items(items)
        print(f"发现 {len(items)} 条，新增 {inserted} 条。")


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


def extract_metadata(soup: BeautifulSoup):
    """
    详情页元数据结构类似：
    [主题分类] 卫生、体育/医药管理
    [发文机构] 北京市医疗保障局
    [实施日期]
    [成文日期] 2026-03-27
    [发文字号] 京医保发〔2026〕3号
    [废止日期]
    [发布日期] 2026-03-27
    [有效性] 是
    [文件来源] 政府公报...
    """
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
        "文件来源": "",
    }

    for key in meta.keys():
        pattern = rf"\[{re.escape(key)}\]\s*([^\n]*)"
        m = re.search(pattern, text)
        if m:
            value = m.group(1).strip()
            value = re.sub(r"\s+", " ", value)
            meta[key] = value

    return meta


def extract_title(soup: BeautifulSoup):
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)

    # 页面正文中标题通常比较靠前
    title = soup.find("title")
    if title:
        return title.get_text(strip=True).replace("_政策文件_首都之窗_北京市人民政府门户网站", "")

    return ""


def extract_content(soup: BeautifulSoup):
    candidates = [
        soup.find("div", class_=re.compile("TRS_Editor|article|content|main|detail", re.I)),
        soup.find("div", id=re.compile("TRS_Editor|article|content|main|detail", re.I)),
        soup.find("body"),
    ]

    content = ""
    for node in candidates:
        if not node:
            continue

        text = node.get_text("\n", strip=True)

        # 去掉明显无关内容
        text = re.sub(r"字号：\s*大\s*中\s*小", "", text)
        text = re.sub(r"分享：\s*X", "", text)
        text = re.sub(r"您访问的链接即将离开.*?放弃", "", text, flags=re.S)

        if len(text) > len(content):
            content = text

    return content.strip()


def is_attachment_url(url: str):
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in ATTACH_EXTS)


def download_attachment(file_url: str, name: str):
    parsed = urlparse(file_url)
    url_name = os.path.basename(parsed.path)
    ext = os.path.splitext(url_name)[1]

    filename = clean_filename(name or url_name or md5_text(file_url))

    if ext and not filename.lower().endswith(ext.lower()):
        filename += ext

    local_path = os.path.join(ATTACH_DIR, filename)

    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return local_path

    resp = request_url(file_url, timeout=60)

    if not resp:
        raise Exception(f"附件请求异常：{file_url}")

    if resp.status_code != 200:
        raise Exception(f"附件下载失败，状态码：{resp.status_code}，URL：{file_url}")

    with open(local_path, "wb") as f:
        f.write(resp.content)

    return local_path


def extract_attachments(soup: BeautifulSoup, detail_url: str):
    attachments = []

    for a in soup.find_all("a"):
        href = a.get("href")
        name = a.get_text(strip=True)

        if not href:
            continue

        file_url = urljoin(detail_url, href)

        if not is_attachment_url(file_url):
            continue

        try:
            local_path = download_attachment(file_url, name)
            attachments.append({
                "附件名称": name or os.path.basename(urlparse(file_url).path),
                "附件URL": file_url,
                "附件本地路径": local_path
            })
            print(f"附件已下载：{local_path}")

        except Exception as e:
            print(f"附件下载失败：{file_url}，原因：{e}")
            attachments.append({
                "附件名称": name or os.path.basename(urlparse(file_url).path),
                "附件URL": file_url,
                "附件本地路径": "",
                "错误": str(e)
            })

    return attachments


def parse_detail_page(detail_url: str):
    resp = request_url(detail_url)

    if not resp:
        raise Exception("详情页请求异常")

    if resp.status_code != 200:
        raise Exception(f"详情页状态码异常：{resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")

    meta = extract_metadata(soup)
    title = extract_title(soup)
    content = extract_content(soup)
    attachments = extract_attachments(soup, detail_url)

    crawl_time = now_str()

    base_data = {
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
        "爬取时间": crawl_time,
        "爬取状态": "done",
        "内容大小": len(content),
    }

    if not attachments:
        row = {
            **base_data,
            "附件名称": "",
            "附件URL": "",
            "附件本地路径": "",
        }
        return [row]

    rows = []
    for att in attachments:
        row = {
            **base_data,
            "附件名称": att.get("附件名称", ""),
            "附件URL": att.get("附件URL", ""),
            "附件本地路径": att.get("附件本地路径", ""),
        }
        rows.append(row)

    return rows


def update_policy_success(policy_id: int, data_rows):
    conn = get_conn()
    cur = conn.cursor()

    first_row = data_rows[0] if data_rows else {}

    cur.execute("""
    UPDATE policies
    SET crawl_status = 'done',
        error_msg = NULL,
        title = COALESCE(NULLIF(?, ''), title),
        publish_date = COALESCE(NULLIF(?, ''), publish_date),
        valid_status = COALESCE(NULLIF(?, ''), valid_status),
        data_json = ?,
        updated_at = ?
    WHERE id = ?
    """, (
        first_row.get("标题", ""),
        first_row.get("发布日期", ""),
        first_row.get("有效性", ""),
        json.dumps(data_rows, ensure_ascii=False),
        now_str(),
        policy_id
    ))

    conn.commit()
    conn.close()


def update_policy_failed(policy_id: int, error_msg: str):
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
            update_policy_success(policy_id, data_rows)
            print(f"完成：{title}")

        except Exception as e:
            update_policy_failed(policy_id, str(e))
            print(f"失败：{title}，原因：{e}")


def export_excel():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    SELECT data_json, detail_url, title, publish_date, valid_status, crawl_status, error_msg, updated_at
    FROM policies
    ORDER BY publish_date DESC, id DESC
    """)

    all_rows = []

    for data_json, detail_url, title, publish_date, valid_status, crawl_status, error_msg, updated_at in cur.fetchall():
        if data_json:
            try:
                rows = json.loads(data_json)
                all_rows.extend(rows)
                continue
            except Exception:
                pass

        # 未成功抓取的也导出，方便排查
        all_rows.append({
            "主题分类": "",
            "标题": title or "",
            "发布日期": publish_date or "",
            "废止日期": "",
            "有效性": valid_status or "",
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
            "内容大小": 0,
        })

    conn.close()

    df = pd.DataFrame(all_rows)

    for field in FIELDS:
        if field not in df.columns:
            df[field] = ""

    df = df[FIELDS]
    df.to_excel(EXCEL_PATH, index=False)

    print(f"Excel 已导出：{EXCEL_PATH}")
    print(f"总行数：{len(df)}")


def add_single_url(detail_url: str, title: str = ""):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    INSERT OR IGNORE INTO policies
    (
        detail_url,
        title,
        publish_date,
        valid_status,
        crawl_status,
        created_at,
        updated_at
    )
    VALUES (?, ?, '', '', 'pending', ?, ?)
    """, (
        detail_url,
        title,
        now_str(),
        now_str()
    ))

    inserted = cur.rowcount

    # 如果之前失败过，可以重新置为 pending
    cur.execute("""
    UPDATE policies
    SET crawl_status = CASE
            WHEN crawl_status = 'failed' THEN 'pending'
            ELSE crawl_status
        END,
        updated_at = ?
    WHERE detail_url = ?
    """, (
        now_str(),
        detail_url
    ))

    conn.commit()
    conn.close()

    return inserted

SINGLE_URLS = [
    "https://www.beijing.gov.cn/zhengce/zhengcefagui/qtwj/200405/t20040525_566608.html",
    "https://www.beijing.gov.cn/zhengce/gfxwj/201905/t20190522_60680.html",
]


def main():
    init_db()

    if SINGLE_URLS:
        print("模式：单网页抓取")

        for url in SINGLE_URLS:
            inserted = add_single_url(url)
            print(f"加入单网页：{url}，新增={inserted}")

        print("抓取详情页和附件")
        crawl_detail_pages()

        print("导出 Excel")
        export_excel()

        print("全部完成")
        return

    print("模式：栏目列表抓取")
    print("第一步：扫描政策法规列表页")
    crawl_list_pages()

    print("第二步：抓取详情页和附件")
    crawl_detail_pages()

    print("第三步：导出 Excel")
    export_excel()

    print("全部完成")


if __name__ == "__main__":
    main()