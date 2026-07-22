import re


def normalize_policy_text(text: str) -> str:
    """
    政策正文清洗：
    - 统一换行
    - 去除多余空白
    - 保留法律条款结构
    """
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)

    # 常见网页噪声
    noise_patterns = [
        r"字号：\s*大\s*中\s*小",
        r"分享：.*",
        r"打印本页",
        r"关闭窗口",
        r"扫一扫在手机打开当前页",
    ]

    for pattern in noise_patterns:
        text = re.sub(pattern, "", text)

    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if line:
            lines.append(line)

    return "\n".join(lines)