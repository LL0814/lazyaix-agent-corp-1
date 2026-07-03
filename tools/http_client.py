"""轻量 HTTP 客户端封装（基础设施，非业务工具）。

所有外部 API 客户端（amap_client / baidu_client / openmeteo_client）
都通过本模块发起 HTTP 请求，统一处理异常与日志，避免重复代码。

本文件提供的函数：
  ┌──────────┬──────────────────────────────────────────────┐
  │ 函数      │ 作用                                          │
  ├──────────┼──────────────────────────────────────────────┤
  │ http_get  │ 发起 GET 请求，返回解析后的 JSON 字典         │
  └──────────┴──────────────────────────────────────────────┘

特性：
  - 统一处理 GET 请求 + JSON 响应解析
  - 异常捕获与日志告警（不抛异常中断流程，失败返回 None）
  - 零依赖（仅用标准库 urllib，不引入 requests/httpx）
  - macOS 兼容：禁用证书校验避免 CERTIFICATE_VERIFY_FAILED
"""

import json
import logging
import ssl
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

# macOS 上 Python 3 默认不信任系统证书，导致 HTTPS 请求报 CERTIFICATE_VERIFY_FAILED。
# 练手项目创建一个不验证证书的 SSL context，避免此问题。
# 生产环境应改用 certifi 或安装系统证书。
_SSL_CONTEXT = ssl.create_default_context()
_SSL_CONTEXT.check_hostname = False
_SSL_CONTEXT.verify_mode = ssl.CERT_NONE


def http_get(url: str, params: dict | None = None, timeout: int = 10) -> dict | None:
    """发起 GET 请求并返回解析后的 JSON 字典。

    Args:
        url: 请求 URL
        params: 查询参数，会自动 url-encode 拼接到 url
        timeout: 超时时间（秒）

    Returns:
        解析后的 JSON 字典；请求失败时返回 None
    """
    # 拼接查询参数
    if params:
        query = urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{url}?{query}"

    try:
        req = Request(url, headers={"User-Agent": "TravelAgent/1.0"})
        with urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except URLError as e:
        logger.warning("HTTP 请求失败: %s | URL: %s", e, url)
        return None
    except json.JSONDecodeError as e:
        logger.warning("JSON 解析失败: %s | URL: %s", e, url)
        return None
    except Exception as e:  # noqa: BLE001 - 兜底，确保不中断主流程
        logger.warning("HTTP 请求异常: %s | URL: %s", e, url)
        return None
