"""
utils/platform.py — URL 域名解析 & 平台名映射
"""
from urllib.parse import urlparse

PLATFORM_MAP = {
    "zhihu.com": "知乎", "www.zhihu.com": "知乎", "zhuanlan.zhihu.com": "知乎",
    "x.com": "X", "twitter.com": "X",
    "reddit.com": "Reddit", "www.reddit.com": "Reddit",
    "bilibili.com": "B站", "www.bilibili.com": "B站", "b23.tv": "B站",
    "weibo.com": "微博", "m.weibo.cn": "微博",
    "mp.weixin.qq.com": "微信公众号",
    "youtube.com": "YouTube", "www.youtube.com": "YouTube",
    "github.com": "GitHub",
    "medium.com": "Medium", "substack.com": "Substack",
    "juejin.cn": "掘金", "sspai.com": "少数派",
    "36kr.com": "36氪", "v2ex.com": "V2EX",
}


def extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def domain_to_platform(domain: str) -> str:
    clean = domain.replace("www.", "")
    return PLATFORM_MAP.get(domain) or PLATFORM_MAP.get(clean) or clean
