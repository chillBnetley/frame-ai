from __future__ import annotations

import base64
import io
import json
import time
from typing import Any
from uuid import uuid4

from PIL import Image

from app.ai.errors import ProviderError
from app.ai.generative import (
    GeneratedImage,
    GenerativeCapabilities,
    GenerativeProviderError,
    GenerativeProviderJob,
    GenerativeRequest,
    GenerativeRequestSpec,
)
from app.ai.generative import validate_spec as validate_capability_spec
from app.ai.generative_transport import GenerativeHttpClient, normalize_generative_error
from app.ai.transport import HttpTransport
from app.models.generative import GenerativeTaskType

DASHSCOPE_SYNTHESIS_PATH = "/api/v1/services/aigc/image2image/image-synthesis"
DASHSCOPE_TASK_PATH = "/api/v1/tasks"

MIN_EDGE = 512
MAX_EDGE = 4096
MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_PROMPT_CHARS = 800
# Base64 inflates by 4/3; keep the encoded payload inside the vendor's 10 MiB cap.
MAX_RAW_BYTES = MAX_INPUT_BYTES * 3 // 4 - 4096
# Beyond 2x a side the masked area has almost no neighbouring context left.
MAX_OUTPAINT_SCALE = 2.0

DEFAULT_PROMPTS: dict[GenerativeTaskType, str] = {
    GenerativeTaskType.OUTPAINT: (
        "自然延续画面构图，让新增区域的内容、光线、色彩与透视和原图一致，不添加突兀的新主体。"
    ),
    GenerativeTaskType.REMOVE: "移除白色区域中的物体，用周围背景自然填补，保持纹理与光线连续。",
    GenerativeTaskType.LOCAL_EDIT: "",
}

RETENTION_NOTICE = (
    "照片会作为 base64 上传到阿里云百炼；异步任务结果 URL 有效期 24 小时，"
    "任务数据在 24 小时后清理（以官方文档为准）。"
)


class DashScopeGenerativeProvider:
    """Alibaba Cloud Bailian ``wanx2.1-imageedit`` adapter.

    Every task type is expressed as ``description_edit_with_mask``: the service
    already builds a same-size canvas plus a white=editable mask, so the vendor
    returns pixels at the requested size and the protected region can be restored
    byte-exactly afterwards.
    """

    name = "dashscope"
    is_mock = False
    prompt_version = "generative-dashscope/1"

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        transport: HttpTransport | None = None,
        timeout: float = 120.0,
        max_retries: int = 1,
        download_max_bytes: int = 96 * 1024 * 1024,
    ) -> None:
        if not api_key:
            raise GenerativeProviderError(
                "generative_provider_not_configured",
                "No DashScope API key is configured.",
            )
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        if transport is None:
            raise GenerativeProviderError(
                "generative_provider_not_configured",
                "The DashScope adapter requires an HTTP transport.",
            )
        self._transport = transport
        self._client = GenerativeHttpClient(
            self._transport,
            binary_max_bytes=download_max_bytes,
        )
        # Result URLs are only known after polling; keep the mapping in memory.
        self._results: dict[str, str] = {}
        self._prompts: dict[str, str] = {}
        # The vendor downscales large inputs to its inference budget (~1 MP), so
        # remember what we asked for and restore that exact canvas afterwards.
        self._targets: dict[str, tuple[int, int]] = {}

    # ------------------------------------------------------------------ spec

    def capabilities(self) -> GenerativeCapabilities:
        return GenerativeCapabilities(
            supported_task_types=(
                GenerativeTaskType.LOCAL_EDIT,
                GenerativeTaskType.OUTPAINT,
                GenerativeTaskType.REMOVE,
            ),
            supports_mask=True,
            supports_multiple_outputs=False,
            supports_async=True,
            supports_cancel=False,
            max_output_pixels=MAX_EDGE * MAX_EDGE,
            max_long_edge=MAX_EDGE,
            allowed_output_formats=("png",),
            declared_retention=RETENTION_NOTICE,
            notes=(
                "真实模型：结果由阿里云百炼生成，照片会离开本机。",
                f"输入与输出边长需在 {MIN_EDGE}–{MAX_EDGE} 像素之间，单张不超过 10 MB。",
                f"扩图每边最多 {MAX_OUTPAINT_SCALE:.1f} 倍。",
                "计费约 0.14 元/张，可在设置中限制每日张数。",
            ),
            min_edge=MIN_EDGE,
            max_outpaint_scale=MAX_OUTPAINT_SCALE,
        )

    def validate_spec(self, spec: GenerativeRequestSpec) -> None:
        validate_capability_spec(self.capabilities(), spec)
        if max(spec.output_width, spec.output_height) > MAX_EDGE:
            raise GenerativeProviderError(
                "generative_input_too_large",
                f"The output canvas is larger than {MAX_EDGE}px on one side.",
                details={"side": max(spec.output_width, spec.output_height), "max": MAX_EDGE},
            )

    def validate_request(self, request: GenerativeRequest) -> None:
        if not request.image.data:
            raise GenerativeProviderError(
                "generative_invalid_input",
                "The provider received an empty image.",
            )
        if request.image.mask is None:
            raise GenerativeProviderError(
                "generative_mask_required",
                "This provider requires a mask for every task type.",
            )
        if request.task_type is not GenerativeTaskType.OUTPAINT:
            return
        outpaint = request.params.get("outpaint")
        if not isinstance(outpaint, dict):
            return
        for axis, target, sides in (
            ("width", request.image.width, ("left", "right")),
            ("height", request.image.height, ("top", "bottom")),
        ):
            margins = [outpaint.get(side) for side in sides]
            total = sum(value for value in margins if isinstance(value, int) and value > 0)
            if total <= 0:
                continue
            base = target - total
            if base <= 0:
                continue
            scale = target / base
            if scale > MAX_OUTPAINT_SCALE + 1e-6:
                raise GenerativeProviderError(
                    "generative_outpaint_scale_exceeded",
                    f"The expansion along {axis} exceeds {MAX_OUTPAINT_SCALE:.1f}x.",
                    details={
                        "axis": axis,
                        "scale": round(scale, 3),
                        "max": MAX_OUTPAINT_SCALE,
                    },
                )

    # -------------------------------------------------------------- lifecycle

    def submit(self, request: GenerativeRequest) -> GenerativeProviderJob:
        prompt = self._prompt_for(request)
        payload = {
            "model": self.model,
            "input": {
                "function": "description_edit_with_mask",
                "prompt": prompt,
                "base_image_url": self._data_uri(request.image.data, request.image.mime_type),
                "mask_image_url": self._data_uri(
                    request.image.mask or b"",
                    request.image.mask_mime_type or "image/png",
                ),
            },
            "parameters": {
                "n": 1,
                "watermark": False,
                "size": f"{request.image.width}*{request.image.height}",
            },
        }
        try:
            response = self._client.submit_json(
                f"{self._base_url}{DASHSCOPE_SYNTHESIS_PATH}",
                payload,
                self._headers(),
                timeout=self._timeout,
                max_retries=self._max_retries,
            )
        except ProviderError as exc:
            raise normalize_generative_error(exc) from None
        output = response.get("output")
        if not isinstance(output, dict):
            raise GenerativeProviderError(
                "generative_provider_invalid_response",
                "The provider response did not contain a task id.",
            )
        task_id = output.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise GenerativeProviderError(
                "generative_provider_invalid_response",
                "The provider response did not contain a task id.",
                details={"requestId": response.get("request_id")},
            )
        self._prompts[task_id] = prompt
        self._targets[task_id] = (request.image.width, request.image.height)
        return GenerativeProviderJob(provider_job_id=task_id, status="queued")

    def poll(self, job: GenerativeProviderJob) -> GenerativeProviderJob:
        task_id = job.provider_job_id
        if not task_id:
            raise GenerativeProviderError(
                "generative_provider_invalid_response",
                "The provider job has no task id.",
            )
        try:
            response = self._client.poll_json(
                f"{self._base_url}{DASHSCOPE_TASK_PATH}/{task_id}",
                self._headers(),
                timeout=self._timeout,
                max_retries=self._max_retries,
            )
        except ProviderError as exc:
            raise normalize_generative_error(exc) from None
        output = response.get("output")
        if not isinstance(output, dict):
            raise GenerativeProviderError(
                "generative_provider_invalid_response",
                "The provider task response was malformed.",
            )
        status = str(output.get("task_status", "")).upper()
        if status in {"PENDING", "SUSPENDED"}:
            return GenerativeProviderJob(provider_job_id=task_id, status="queued")
        if status == "RUNNING":
            return GenerativeProviderJob(provider_job_id=task_id, status="processing")
        if status == "SUCCEEDED":
            url = self._first_result_url(output)
            if url is None:
                raise GenerativeProviderError(
                    "generative_provider_invalid_response",
                    "The provider finished without a result image.",
                )
            self._results[task_id] = url
            return GenerativeProviderJob(provider_job_id=task_id, status="succeeded")
        if status == "CANCELED":
            return GenerativeProviderJob(
                provider_job_id=task_id,
                status="failed",
                error_code="generative_provider_cancelled",
                error_message="The provider cancelled the task.",
            )
        code = output.get("code")
        message = output.get("message")
        return GenerativeProviderJob(
            provider_job_id=task_id,
            status="failed",
            error_code=_error_code(code),
            error_message=str(message or "The provider task failed."),
        )

    def fetch(self, job: GenerativeProviderJob) -> GeneratedImage:
        task_id = job.provider_job_id
        url = self._results.pop(task_id or "", None)
        if task_id is None or url is None:
            raise GenerativeProviderError(
                "generative_provider_invalid_response",
                "The provider result is no longer available.",
            )
        try:
            data, content_type = self._client.download(
                url,
                {},
                timeout=self._timeout,
                max_retries=self._max_retries,
            )
        except ProviderError as exc:
            if exc.code == "provider_endpoint_error":
                raise GenerativeProviderError(
                    "generative_provider_result_download_failed",
                    "The generated image could not be downloaded from the provider CDN.",
                ) from None
            raise normalize_generative_error(exc) from None
        try:
            with Image.open(io.BytesIO(data)) as opened:
                width, height = opened.size
                image_format = (opened.format or "").lower()
        except Exception as exc:  # noqa: BLE001 - vendor bytes are untrusted
            raise GenerativeProviderError(
                "generative_provider_invalid_response",
                "The provider returned an unreadable image.",
            ) from exc
        if image_format not in {"png", "jpeg", "jpg"}:
            raise GenerativeProviderError(
                "generative_provider_invalid_response",
                "The provider returned an unsupported image format.",
                details={"format": image_format},
            )
        target = self._targets.pop(task_id, None)
        data, width, height, resized_from = _fit_to_target(data, width, height, target)
        prompt = self._prompts.pop(task_id, "")
        return GeneratedImage(
            data=data,
            mime_type="image/png" if resized_from else (
                content_type or ("image/png" if image_format == "png" else "image/jpeg")
            ),
            width=width,
            height=height,
            provider_job_id=task_id,
            metadata={
                "provider": self.name,
                "model": self.model,
                "promptChars": len(prompt),
                **({"resizedFrom": resized_from} if resized_from else {}),
            },
        )

    def cancel(self, job: GenerativeProviderJob) -> None:
        # DashScope exposes no cancel endpoint for image synthesis; the service
        # marks the task cancelled and discards whatever arrives later.
        return None

    def check_connection(self, *, timeout: float | None = None) -> int:
        """Verify the submit route and credentials without creating a task.

        The model name is deliberately bogus: a reachable, correctly routed
        endpoint answers 400 ``InvalidParameter`` (no task, no charge), while a
        wrong path/region gives 404 and bad credentials give 401/403.
        """

        probe_timeout = self._timeout if timeout is None else timeout
        started = time.perf_counter()
        body = json.dumps(
            {"model": f"frame-ai-probe-{uuid4().hex[:8]}", "input": {}},
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            response = self._transport.request(
                "POST",
                f"{self._base_url}{DASHSCOPE_SYNTHESIS_PATH}",
                body,
                self._headers(),
                probe_timeout,
                64 * 1024,
            )
        except ProviderError as exc:
            raise normalize_generative_error(exc) from None
        if response.status in {401, 403}:
            raise GenerativeProviderError(
                "generative_provider_auth_failed",
                "The provider rejected the configured credentials.",
                details={"status": response.status},
            )
        if response.status == 404:
            raise GenerativeProviderError(
                "generative_provider_endpoint_error",
                "The configured provider endpoint does not serve this model.",
                details={"status": response.status},
            )
        if response.status >= 500:
            raise GenerativeProviderError(
                "generative_provider_unavailable",
                "The provider is temporarily unavailable.",
                retryable=True,
                details={"status": response.status},
            )
        return int((time.perf_counter() - started) * 1000.0)

    # ---------------------------------------------------------------- helpers

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }

    def _prompt_for(self, request: GenerativeRequest) -> str:
        text = request.instruction.strip()
        if not text:
            text = DEFAULT_PROMPTS.get(request.task_type, "")
        return text[:MAX_PROMPT_CHARS]

    def _data_uri(self, data: bytes, mime_type: str) -> str:
        payload, resolved_mime = self._shrink(data, mime_type)
        encoded = base64.b64encode(payload).decode("ascii")
        return f"data:{resolved_mime};base64,{encoded}"

    @staticmethod
    def _shrink(data: bytes, mime_type: str) -> tuple[bytes, str]:
        if len(data) <= MAX_RAW_BYTES:
            return data, mime_type
        try:
            with Image.open(io.BytesIO(data)) as opened:
                rgb = opened.convert("RGB")
        except Exception as exc:  # noqa: BLE001 - local pixels are trusted, bytes may not be
            raise GenerativeProviderError(
                "generative_input_too_large",
                "The image exceeds the provider size limit and could not be re-encoded.",
            ) from exc
        for quality in (92, 85, 75):
            buffer = io.BytesIO()
            rgb.save(buffer, format="JPEG", quality=quality, optimize=True)
            candidate = buffer.getvalue()
            if len(candidate) <= MAX_RAW_BYTES:
                return candidate, "image/jpeg"
        raise GenerativeProviderError(
            "generative_input_too_large",
            "The image is too large to send to the provider.",
            details={"bytes": len(data), "maxBytes": MAX_INPUT_BYTES},
        )

    @staticmethod
    def _first_result_url(output: dict[str, Any]) -> str | None:
        results = output.get("results")
        if not isinstance(results, list) or not results:
            return None
        first = results[0]
        if not isinstance(first, dict):
            return None
        url = first.get("url")
        return url if isinstance(url, str) and url else None


ASPECT_TOLERANCE = 0.02


def _fit_to_target(
    data: bytes,
    width: int,
    height: int,
    target: tuple[int, int] | None,
) -> tuple[bytes, int, int, str | None]:
    """Scale the vendor result back to the canvas we submitted.

    The vendor caps inference at roughly one megapixel and answers at that
    resolution, so the returned size never matches a large photo. Rescaling is
    safe only while the aspect ratio survives; otherwise the composition no
    longer aligns with the protected region and the task must fail loudly.
    """

    if target is None or (width, height) == target:
        return data, width, height, None
    target_width, target_height = target
    width_ratio = width / target_width
    height_ratio = height / target_height
    if abs(width_ratio - height_ratio) / max(width_ratio, height_ratio) > ASPECT_TOLERANCE:
        raise GenerativeProviderError(
            "generative_invalid_output_size",
            "The provider returned an image whose aspect ratio does not match the request.",
            details={
                "expected": [target_width, target_height],
                "actual": [width, height],
            },
        )
    with Image.open(io.BytesIO(data)) as opened:
        fitted = opened.convert("RGB").resize(
            (target_width, target_height),
            Image.Resampling.LANCZOS,
        )
    buffer = io.BytesIO()
    fitted.save(buffer, format="PNG", optimize=True)
    return (
        buffer.getvalue(),
        target_width,
        target_height,
        f"{width}x{height}",
    )


def _error_code(code: Any) -> str:
    mapping = {
        "InvalidParameter": "generative_provider_invalid_response",
        "DataInspectionFailed": "generative_provider_rejected_content",
        "Throttling": "generative_provider_rate_limited",
        "Arrearage": "generative_provider_budget_exceeded",
    }
    if isinstance(code, str):
        return mapping.get(code, "generative_provider_error")
    return "generative_provider_error"


__all__ = [
    "DASHSCOPE_SYNTHESIS_PATH",
    "DASHSCOPE_TASK_PATH",
    "DashScopeGenerativeProvider",
    "MAX_EDGE",
    "MIN_EDGE",
    "RETENTION_NOTICE",
]
