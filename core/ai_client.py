"""
阿里云百炼（Alibaba Cloud Model Studio / Qwen）AI 客户端。

通过中国北京地域的 OpenAI 兼容 Chat Completions 接口调用千问文本与视觉模型，
用于将 PDF / Excel / Word / 图片内容提取为严格 JSON。只有用户主动执行
“AI 导入”时才会联网并发送所选文件的内容。
"""
import base64
import json
from urllib.parse import urlparse

import requests


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# flash 系列在表格列对齐（数量/单价/金额混淆）上错误较多，升级为 plus 系列：
# 单次 PO 导入约数千 token，费用仍不足 0.01 元。
DEFAULT_TEXT_MODEL = "qwen-plus"
DEFAULT_VISION_MODEL = "qwen3-vl-plus"
REQUEST_TIMEOUT = (15, 120)


class AIClientError(Exception):
    """AI 调用失败时抛出，内容可直接显示给用户。"""


def _validate_base_url(base_url: str) -> str:
    url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise AIClientError(
            "API 地址格式不正确。请使用完整的 HTTPS 地址，例如：\n"
            f"{DEFAULT_BASE_URL}"
        )
    return url


def _extract_api_error(resp: requests.Response) -> str:
    try:
        data = resp.json()
        error = data.get("error", data)
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or error)
        return str(error)
    except (ValueError, json.JSONDecodeError):
        return resp.text[:500].strip() or "服务器未返回错误详情"


def _post_chat_completion(
    api_key: str,
    base_url: str,
    model: str,
    messages: list,
    *,
    json_mode: bool = True,
) -> str:
    if not api_key:
        raise AIClientError(
            "尚未设置阿里云百炼 API Key，请先在“设置”页签中填写并保存。"
        )

    url = f"{_validate_base_url(base_url)}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        # 同一文件多次导入应得到相同结果（此前 PI 与 CI/PL 分别导入同一订单，合计件数不一致）
        "temperature": 0,
        "seed": 1234,
        # 字段提取不需要深度思考；关闭可避免混合思考模型更慢、更贵，且 JSON Mode 不支持思考模式
        "enable_thinking": False,
    }
    if json_mode:
        # Qwen JSON Mode要求提示词中出现“JSON”；现有提取提示词均满足此条件。
        payload["response_format"] = {"type": "json_object"}

    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.SSLError as exc:
        raise AIClientError(
            "与阿里云百炼建立安全连接失败。请检查系统时间、VPN、代理或杀毒软件的 "
            f"HTTPS 扫描设置。\n技术详情：{exc}"
        ) from exc
    except requests.exceptions.ProxyError as exc:
        raise AIClientError(
            "代理服务器连接失败。请检查 Windows 代理/VPN 设置，或暂时关闭代理后重试。"
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        raise AIClientError(
            "无法连接阿里云百炼 API。请检查网络连接，并确认可访问 dashscope.aliyuncs.com。"
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise AIClientError("请求阿里云百炼 API 超时，请稍后重试。") from exc
    except requests.exceptions.RequestException as exc:
        raise AIClientError(f"请求阿里云百炼 API 时发生错误：{exc}") from exc

    if resp.status_code == 401:
        raise AIClientError(
            "阿里云百炼 API Key 无效、地域不匹配或已失效。请确认使用中国北京地域的 Key。"
        )
    if resp.status_code == 403:
        raise AIClientError(
            f"阿里云百炼拒绝了请求。请确认已开通模型服务及相关模型权限。\n{_extract_api_error(resp)}"
        )
    if resp.status_code == 429:
        raise AIClientError(
            "阿里云百炼请求过于频繁或账户额度不足，请稍后重试或检查账户余额。"
        )
    if resp.status_code != 200:
        raise AIClientError(
            f"阿里云百炼返回错误（HTTP {resp.status_code}）：{_extract_api_error(resp)}"
        )

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("返回内容为空")
        return content
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AIClientError(f"阿里云百炼返回了无法解析的响应：{exc}") from exc


def test_connection(api_key: str, base_url: str, text_model: str) -> None:
    """发送最小非 JSON 请求，验证 Key、地域、地址与文本模型。"""
    _post_chat_completion(
        api_key,
        base_url,
        text_model,
        [{"role": "user", "content": "Reply with OK only."}],
        json_mode=False,
    )


def extract_from_text(
    api_key: str, base_url: str, model: str, prompt: str, source_text: str
) -> str:
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": source_text},
    ]
    return _post_chat_completion(api_key, base_url, model, messages)


def extract_from_image(
    api_key: str,
    base_url: str,
    model: str,
    prompt: str,
    image_bytes: bytes,
    mime_type: str = "image/png",
) -> str:
    return extract_from_images(api_key, base_url, model, prompt, [image_bytes], mime_type)


def extract_from_images(
    api_key: str,
    base_url: str,
    model: str,
    prompt: str,
    images: list,
    mime_type: str = "image/png",
    extra_text: str = "",
) -> str:
    """
    多张图片（如多页扫描件）放在同一次请求中，由模型合并提取为一份 JSON。
    extra_text 为同一文件中有文字层页面的内容（混合 PDF），与图片一起提供。
    """
    content = [
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64," + base64.b64encode(img).decode("ascii"),
            },
        }
        for img in images
    ]
    hint = "请识别并提取这份文件中的字段，只返回有效 JSON。"
    if len(images) > 1:
        hint = f"以下 {len(images)} 张图片是同一份文件的连续页面，请合并提取全部字段，只返回有效 JSON。"
    if extra_text.strip():
        hint += "\n\n同一文件中其余页面的文字内容如下，请与图片内容合并提取：\n\n" + extra_text
    content.append({"type": "text", "text": hint})
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": content},
    ]
    return _post_chat_completion(api_key, base_url, model, messages)
