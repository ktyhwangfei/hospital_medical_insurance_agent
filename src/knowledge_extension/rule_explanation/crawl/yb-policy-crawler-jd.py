import os
import re
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

BASE_URL = "https://ybj.beijing.gov.cn/zwgk/2020_zfxxgk/2020_xxgkml/202501/t20250120_3994118.html"
SAVE_DIR = "./raw"
ATTACH_DIR = os.path.join(SAVE_DIR, "attachments")
EXCEL_PATH = os.path.join(SAVE_DIR, "北京市医保局政策解读2.xlsx")

os.makedirs(ATTACH_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
}

ATTACH_EXTS = [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".txt"]


def clean_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name.strip()[:150]


def get_html(url: str) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = resp.apparent_encoding
        if resp.status_code == 200:
            return resp.text
        print(f"请求失败：{url}，状态码：{resp.status_code}")
        return ""
    except Exception as e:
        print(f"请求异常：{url}，错误：{e}")
        return ""


def guess_list_pages(max_pages=50):
    """
    常见政府网站分页规则：
    第1页：index.html 或栏目根目录
    第2页：index_1.html
    第3页：index_2.html
    """
    urls = [BASE_URL]
    for i in range(1, max_pages):
        urls.append(urljoin(BASE_URL, f"index_{i}.html"))
    return urls


def parse_list_page(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    results = []

    # 根据页面实际结构：政策文件列表一般是 a 标签 + 日期文本
    for a in soup.find_all("a"):
        title = a.get_text(strip=True)
        href = a.get("href")

        if not title or not href:
            continue

        full_url = urljoin(page_url, href)

        # 过滤非详情页链接
        if "2024zcwj" not in full_url and "zwgk" not in full_url:
            continue

        parent_text = a.parent.get_text(" ", strip=True) if a.parent else ""
        date_match = re.search(r"\d{4}-\d{2}-\d{2}", parent_text)
        pub_date = date_match.group(0) if date_match else ""

        # 标题太短或明显是导航的过滤掉
        if len(title) < 8:
            continue
        if title in ["首页", "政策文件", "政务公开", "政策解读"]:
            continue

        results.append({
            "标题": title,
            "发布日期": pub_date,
            "详情页URL": full_url
        })

    return results


def parse_detail_page(url):
    html = get_html(url)
    time.sleep(1)

    if not html:
        return "", []

    soup = BeautifulSoup(html, "html.parser")

    # 尽量提取正文区域
    candidates = [
        soup.find("div", class_=re.compile("TRS_Editor|content|article|main", re.I)),
        soup.find("div", id=re.compile("content|article|main", re.I)),
        soup.find("body")
    ]

    content = ""
    for c in candidates:
        if c:
            content = c.get_text("\n", strip=True)
            if len(content) > 100:
                break

    attachments = []
    for a in soup.find_all("a"):
        href = a.get("href")
        name = a.get_text(strip=True)

        if not href:
            continue

        full_url = urljoin(url, href)
        path = urlparse(full_url).path.lower()

        if any(path.endswith(ext) for ext in ATTACH_EXTS):
            local_path = download_attachment(full_url, name)
            attachments.append({
                "附件名称": name or os.path.basename(path),
                "附件URL": full_url,
                "附件本地路径": local_path
            })

    return content, attachments


def download_attachment(file_url, name=""):
    try:
        filename = name or os.path.basename(urlparse(file_url).path)
        filename = clean_filename(filename)

        # 如果文件名没有扩展名，从 URL 补
        ext = os.path.splitext(urlparse(file_url).path)[1]
        if ext and not filename.lower().endswith(ext.lower()):
            filename += ext

        local_path = os.path.join(ATTACH_DIR, filename)

        if os.path.exists(local_path):
            return local_path

        resp = requests.get(file_url, headers=HEADERS, timeout=30)
        if resp.status_code == 200:
            with open(local_path, "wb") as f:
                f.write(resp.content)
            print(f"附件已下载：{local_path}")
            return local_path
        else:
            print(f"附件下载失败：{file_url}，状态码：{resp.status_code}")
            return ""

    except Exception as e:
        print(f"附件下载异常：{file_url}，错误：{e}")
        return ""


def main():
    all_items = []
    seen_urls = set()

    for page_url in guess_list_pages(max_pages=50):
        print(f"正在抓取列表页：{page_url}")
        html = get_html(page_url)
        time.sleep(1)

        if not html:
            continue

        items = parse_list_page(html, page_url)

        if not items:
            print(f"未发现政策文件，跳过：{page_url}")
            continue

        for item in items:
            if item["详情页URL"] in seen_urls:
                continue

            seen_urls.add(item["详情页URL"])

            print(f"正在抓取详情页：{item['标题']}")
            content, attachments = parse_detail_page(item["详情页URL"])

            if attachments:
                for att in attachments:
                    row = {
                        **item,
                        "正文内容": content,
                        "附件名称": att["附件名称"],
                        "附件URL": att["附件URL"],
                        "附件本地路径": att["附件本地路径"]
                    }
                    all_items.append(row)
            else:
                row = {
                    **item,
                    "正文内容": content,
                    "附件名称": "",
                    "附件URL": "",
                    "附件本地路径": ""
                }
                all_items.append(row)

    df = pd.DataFrame(all_items)
    df.to_excel(EXCEL_PATH, index=False)
    print(f"完成，共抓取 {len(df)} 条记录，已保存：{EXCEL_PATH}")


if __name__ == "__main__":
    main()