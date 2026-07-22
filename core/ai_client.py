"""
智谱 AI (Zhipu / BigModel) 客户端
通过智谱开放平台的 OpenAI 兼容 Chat Completions 接口调用 GLM 模型，
用于从 PDF/Excel/图片中提取结构化字段（OCR + 信息抽取一体）。

默认使用 GLM-4-Flash（文本）与 GLM-4V-Flash（视觉），两者目前均为免费模型
（有请求频率限制，具体以智谱开放平台当前政策为准）。

注意：此功能需要联网，并会将文件内容发送至智谱云端 API，
与本软件其余功能的"纯本地单机"设计不同，仅在用户主动点击"AI 导入"时才会触发。
"""
import base64
import json

import requests

DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_TEXT_MODEL = "glm-4-flash"
DEFAULT_VISION_MODEL = "glm-4v-flash"

REQUEST_TIMEOUT = 60


class AIClientError(Exception):
    """AI 调用失败时抛出，携带用户可读的错误信息"""
    pass


def _post_chat_completion(api_key: str, base_url: str, model: str, messages: list) -> str:
    if not api_key:
        raise AIClientError("尚未设置智谱 AI API Key，请先在「设置」页签中填写。")

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.ConnectionError:
        raise AIClientError("无法连接智谱 AI API，请检查网络连接。")
    except requests.exceptions.Timeout:
        raise AIClientError("请求智谱 AI API 超时，请稍后重试。")
    except requests.exceptions.RequestException as e:
        raise AIClientError(f"请求智谱 AI API 时发生错误：{e}")

    if resp.status_code == 401:
        raise AIClientError("智谱 AI API Key 无效或已过期，请在「设置」页签中检查。")
    if resp.status_code == 429:
        raise AIClientError("智谱 AI API 请求过于频繁或额度不足，请稍后重试。")
    if resp.status_code != 200:
        raise AIClientError(f"智谱 AI API 返回错误（状态码 {resp.status_code}）：{resp.text[:300]}")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
        raise AIClientError(f"智谱 AI API 返回了无法解析的响应：{e}")

    return content


def test_connection(api_key: str, base_url: str, text_model: str) -> None:
    """发送一次最小请求以验证 API Key 是否有效。失败时抛出 AIClientError。"""
    messages = [{"role": "user", "content": "OK"}]
    _post_chat_completion(api_key, base_url, text_model, messages)


def extract_from_text(api_key: str, base_url: str, model: str, prompt: str, source_text: str) -> str:
    """将文本内容连同提示词发送给智谱文本模型，返回模型的原始回复文本"""
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": source_text},
    ]
    return _post_chat_completion(api_key, base_url, model, messages)


def extract_from_image(api_key: str, base_url: str, model: str, prompt: str, image_bytes: bytes,
                        mime_type: str = "image/png") -> str:
    """将图片（JPG/PNG 或 PDF 页面渲染图）连同提示词发送给智谱视觉模型，返回模型的原始回复文本"""
    b64_image = base64.b64encode(image_bytes).decode("ascii")
    data_uri = f"data:{mime_type};base64,{b64_image}"
    messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_uri}},
                {"type": "text", "text": "请识别并提取这份文件中的字段。"},
            ],
        },
    ]
    return _post_chat_completion(api_key, base_url, model, messages)
