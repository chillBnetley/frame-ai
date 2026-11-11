from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from app.ai.generative import (
    GenerativeImageInput,
    GenerativeProviderError,
    GenerativeProviderJob,
    GenerativeRequest,
    GenerativeRequestSpec,
)
from app.ai.providers import generative_dashscope as module
from app.ai.providers.generative_dashscope import DashScopeGenerativeProvider
from app.ai.transport import HttpResponse
from app.models.generative import GenerativeTaskType

BASE_URL = "https://dashscope.aliyuncs.com"


def _png(width: int, height: int, color=(120, 130, 140), *, noisy: bool = False) -> bytes:
    buffer = io.BytesIO()
    if noisy:
        pixels = Image.effect_noise((width, height), 48).convert("RGB")
    else:
        pixels = Image.new("RGB", (width, height), color)
    pixels.save(buffer, format="PNG")
    return buffer.getvalue()


class FakeTransport:
    """Records requests and replies from a per-URL script."""

    def __init__(self, responses: list[tuple[int, dict[str, str], bytes]] | None = None) -> None:
        self.requests: list[tuple[str, str, bytes | None, dict[str, str]]] = []
        self.responses = list(responses or [])

    def queue(self, status: int, payload: dict[str, object] | bytes, headers=None) -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.responses.append((status, headers or {}, body))

    def request(self, method, url, body, headers, timeout, max_response_bytes):
        self.requests.append((method, url, body, dict(headers)))
        if not self.responses:
            raise AssertionError(f"unexpected request: {method} {url}")
        status, response_headers, response_body = self.responses.pop(0)
        return HttpResponse(status=status, body=response_body, headers=response_headers)


def _provider(transport: FakeTransport, *, max_retries: int = 1) -> DashScopeGenerativeProvider:
    return DashScopeGenerativeProvider(
        model="wanx2.1-imageedit",
        api_key="sk-test",
        base_url=BASE_URL,
        transport=transport,
        max_retries=max_retries,
    )


def _request(
    *,
    task_type: GenerativeTaskType = GenerativeTaskType.LOCAL_EDIT,
    width: int = 640,
    height: int = 480,
    instruction: str = "把天空换成晚霞",
    params: dict[str, object] | None = None,
    noisy: bool = False,
) -> GenerativeRequest:
    return GenerativeRequest(
        task_id="task-1",
        task_type=task_type,
        instruction=instruction,
        image=GenerativeImageInput(
            data=_png(width, height, noisy=noisy),
            mime_type="image/png",
            width=width,
            height=height,
            mask=_png(width, height, (255, 255, 255)),
            mask_mime_type="image/png",
        ),
        params=params or {},
    )


def test_submit_polls_and_fetches_the_generated_image():
    transport = FakeTransport()
    transport.queue(200, {"output": {"task_id": "t-1", "task_status": "PENDING"}})
    transport.queue(200, {"output": {"task_id": "t-1", "task_status": "RUNNING"}})
    transport.queue(
        200,
        {
            "output": {
                "task_id": "t-1",
                "task_status": "SUCCEEDED",
                "results": [{"url": "https://result.example/out.png"}],
            }
        },
    )
    transport.queue(
        200,
        _png(640, 480),
        {"content-type": "image/png"},
    )

    provider = _provider(transport)
    request = _request()
    provider.validate_request(request)
    job = provider.submit(request)

    assert job.status == "queued"
    submit_url, submit_body, submit_headers = (
        transport.requests[0][1],
        transport.requests[0][2],
        transport.requests[0][3],
    )
    assert submit_url == f"{BASE_URL}/api/v1/services/aigc/image2image/image-synthesis"
    payload = json.loads(submit_body or b"{}")
    assert payload["model"] == "wanx2.1-imageedit"
    assert payload["input"]["function"] == "description_edit_with_mask"
    assert payload["input"]["prompt"] == "把天空换成晚霞"
    assert payload["input"]["base_image_url"].startswith("data:image/png;base64,")
    assert payload["input"]["mask_image_url"].startswith("data:image/png;base64,")
    assert payload["parameters"]["size"] == "640*480"
    assert submit_headers["X-DashScope-Async"] == "enable"
    assert submit_headers["Authorization"] == "Bearer sk-test"

    job = provider.poll(job)
    assert job.status == "processing"
    job = provider.poll(job)
    assert job.status == "succeeded"

    image = provider.fetch(job)
    assert (image.width, image.height) == (640, 480)
    assert image.mime_type == "image/png"


def test_failed_task_maps_vendor_code():
    transport = FakeTransport()
    transport.queue(200, {"output": {"task_id": "t-2", "task_status": "PENDING"}})
    transport.queue(
        200,
        {
            "output": {
                "task_id": "t-2",
                "task_status": "FAILED",
                "code": "Throttling",
                "message": "busy",
            }
        },
    )
    provider = _provider(transport)
    job = provider.submit(_request())
    job = provider.poll(job)
    assert job.status == "failed"
    assert job.error_code == "generative_provider_rate_limited"
    assert job.error_message == "busy"


def test_rejects_images_smaller_than_the_provider_minimum():
    provider = _provider(FakeTransport())
    spec = GenerativeRequestSpec(
        task_type=GenerativeTaskType.OUTPAINT,
        instruction="",
        has_mask=True,
        candidates=1,
        input_width=480,
        input_height=320,
        target_width=640,
        target_height=640,
    )
    with pytest.raises(GenerativeProviderError) as excinfo:
        provider.validate_spec(spec)
    assert excinfo.value.code == "generative_input_too_small"
    assert excinfo.value.details == {"shortEdge": 320, "minEdge": 512}


def test_rejects_outpaint_expansion_beyond_two_times():
    transport = FakeTransport()
    provider = _provider(transport)
    request = _request(
        task_type=GenerativeTaskType.OUTPAINT,
        width=2700,
        height=800,
        params={"outpaint": {"top": 0, "bottom": 0, "left": 750, "right": 750}},
    )
    with pytest.raises(GenerativeProviderError) as excinfo:
        provider.validate_request(request)
    assert excinfo.value.code == "generative_outpaint_scale_exceeded"
    assert excinfo.value.details["axis"] == "width"
    assert excinfo.value.details["scale"] == 2.25


def test_prompt_is_truncated_to_the_vendor_limit():
    transport = FakeTransport()
    transport.queue(200, {"output": {"task_id": "t-3", "task_status": "PENDING"}})
    provider = _provider(transport)
    provider.submit(_request(instruction="字" * 1200))
    payload = json.loads(transport.requests[0][2] or b"{}")
    assert len(payload["input"]["prompt"]) == 800


def test_outpaint_defaults_to_a_continuation_prompt():
    transport = FakeTransport()
    transport.queue(200, {"output": {"task_id": "t-4", "task_status": "PENDING"}})
    provider = _provider(transport)
    provider.submit(
        _request(
            task_type=GenerativeTaskType.OUTPAINT,
            instruction="",
            params={"outpaint": {"top": 100, "bottom": 100, "left": 0, "right": 0}},
        )
    )
    payload = json.loads(transport.requests[0][2] or b"{}")
    assert "自然延续画面构图" in payload["input"]["prompt"]


def test_check_connection_treats_a_missing_task_as_reachable():
    transport = FakeTransport()
    transport.queue(404, {"code": "NotFound"})
    provider = _provider(transport)
    assert provider.check_connection(timeout=1.0) >= 0


def test_check_connection_reports_bad_credentials():
    transport = FakeTransport()
    transport.queue(401, {"code": "InvalidApiKey"})
    provider = _provider(transport)
    with pytest.raises(GenerativeProviderError) as excinfo:
        provider.check_connection(timeout=1.0)
    assert excinfo.value.code == "generative_provider_auth_failed"


def test_fetch_rejects_non_image_payloads():
    transport = FakeTransport()
    transport.queue(200, {"output": {"task_id": "t-5", "task_status": "PENDING"}})
    transport.queue(
        200,
        {
            "output": {
                "task_id": "t-5",
                "task_status": "SUCCEEDED",
                "results": [{"url": "https://result.example/out.png"}],
            }
        },
    )
    transport.queue(200, b"not an image", {"content-type": "image/png"})
    provider = _provider(transport)
    job = provider.submit(_request())
    job = provider.poll(job)
    with pytest.raises(GenerativeProviderError) as excinfo:
        provider.fetch(job)
    assert excinfo.value.code == "generative_provider_invalid_response"


def test_oversized_payload_is_re_encoded_to_jpeg(monkeypatch):
    png = _png(640, 480, noisy=True)
    jpeg_buffer = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGB").save(jpeg_buffer, format="JPEG", quality=92)
    jpeg = jpeg_buffer.getvalue()
    assert len(jpeg) < len(png)
    # Any limit between the two encodings forces the adapter to switch formats.
    monkeypatch.setattr(module, "MAX_RAW_BYTES", (len(png) + len(jpeg)) // 2)
    transport = FakeTransport()
    transport.queue(200, {"output": {"task_id": "t-6", "task_status": "PENDING"}})
    provider = _provider(transport)
    provider.submit(_request(width=640, height=480, noisy=True))
    payload = json.loads(transport.requests[0][2] or b"{}")
    assert payload["input"]["base_image_url"].startswith("data:image/jpeg;base64,")


def test_provider_rejects_requests_without_a_mask():
    provider = _provider(FakeTransport())
    request = GenerativeRequest(
        task_id="task-2",
        task_type=GenerativeTaskType.REMOVE,
        instruction="去掉路人",
        image=GenerativeImageInput(
            data=_png(640, 480),
            mime_type="image/png",
            width=640,
            height=480,
        ),
    )
    with pytest.raises(GenerativeProviderError) as excinfo:
        provider.validate_request(request)
    assert excinfo.value.code == "generative_mask_required"


def test_transport_errors_are_normalized():
    transport = FakeTransport()
    transport.queue(429, {"code": "Throttling"})
    provider = _provider(transport, max_retries=0)
    with pytest.raises(GenerativeProviderError) as excinfo:
        provider.submit(_request())
    assert excinfo.value.code == "generative_provider_rate_limited"


def test_cancel_is_a_noop_because_the_vendor_has_no_cancel_endpoint():
    provider = _provider(FakeTransport())
    assert provider.capabilities().supports_cancel is False
    provider.cancel(GenerativeProviderJob(provider_job_id="t-7", status="processing"))
