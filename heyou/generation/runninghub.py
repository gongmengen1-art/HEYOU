"""RunningHub cloud ComfyUI backend: upload portrait -> create task -> poll -> download.

The image-upload endpoint and field names are confirmed from the official plugin source.
The create/status/outputs payloads follow the documented RunningHub OpenAPI pattern; the
response parsing is defensive (accepts a few shapes) and includes the raw JSON in errors so
the first real run is easy to debug.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)


class RunningHubError(RuntimeError):
    pass


class RunningHubBackend:
    name = "runninghub"

    def __init__(self, cfg):
        rh = cfg.generation.runninghub
        self.base = rh.base_url.rstrip("/")
        self.api_key = cfg.comfyui.runninghub_api_key
        self.workflow_id = rh.workflow_id
        self.input_image_node_id = rh.input_image_node_id
        self.seed_node_id = rh.seed_node_id
        self.prompt_node_id = rh.prompt_node_id
        self.poll_interval = rh.poll_interval_sec
        self.timeout = rh.timeout_sec
        if not self.api_key:
            raise RunningHubError("comfyui.runninghub_api_key is not set in config.yaml")
        if not self.workflow_id:
            raise RunningHubError(
                "generation.runninghub.workflow_id is empty — run the workflow once and set it (step 0a)"
            )

    # ---- low-level calls ---------------------------------------------------
    def _post(self, client: httpx.Client, path: str, **kwargs) -> dict:
        r = client.post(f"{self.base}{path}", **kwargs)
        r.raise_for_status()
        j = r.json()
        if j.get("code") not in (0, "0"):
            raise RunningHubError(f"{path} -> {j}")
        return j

    def _upload_image(self, client: httpx.Client, path: str | Path) -> str:
        with open(path, "rb") as f:
            files = {"file": (Path(path).name, f, "image/png")}
            data = {"apiKey": self.api_key, "fileType": "image"}
            j = self._post(client, "/task/openapi/upload", data=data, files=files)
        fn = (j.get("data") or {}).get("fileName")
        if not fn:
            raise RunningHubError(f"no fileName in upload response: {j}")
        return fn

    def _node_info_list(self, image_filename: str, seed: int, prompt: str) -> list[dict]:
        items: list[dict] = []
        if self.input_image_node_id:
            items.append({"nodeId": self.input_image_node_id, "fieldName": "image", "fieldValue": image_filename})
        if self.seed_node_id:
            items.append({"nodeId": self.seed_node_id, "fieldName": "seed", "fieldValue": seed})
        if self.prompt_node_id and prompt:
            items.append({"nodeId": self.prompt_node_id, "fieldName": "text", "fieldValue": prompt})
        return items

    def _create_task(self, client: httpx.Client, image_filename: str, seed: int, prompt: str) -> str:
        payload = {
            "apiKey": self.api_key,
            "workflowId": self.workflow_id,
            "nodeInfoList": self._node_info_list(image_filename, seed, prompt),
        }
        j = self._post(client, "/task/openapi/create", json=payload)
        data = j.get("data") or {}
        task_id = data.get("taskId") if isinstance(data, dict) else None
        if not task_id:
            raise RunningHubError(f"no taskId in create response: {j}")
        return str(task_id)

    def _task_status(self, client: httpx.Client, task_id: str) -> str:
        j = self._post(client, "/task/openapi/status", json={"apiKey": self.api_key, "taskId": task_id})
        data = j.get("data")
        if isinstance(data, dict):
            return str(data.get("taskStatus") or data.get("status") or data)
        return str(data)

    def _task_outputs(self, client: httpx.Client, task_id: str) -> list[str]:
        j = self._post(client, "/task/openapi/outputs", json={"apiKey": self.api_key, "taskId": task_id})
        urls: list[str] = []
        for item in j.get("data") or []:
            if isinstance(item, dict):
                u = item.get("fileUrl") or item.get("url")
                if u:
                    urls.append(u)
            elif isinstance(item, str):
                urls.append(item)
        return urls

    # ---- public API --------------------------------------------------------
    def run_task(self, portrait_path: str, seed: int, prompt: str = "") -> list[str]:
        """Run the workflow once; return the list of output image URLs."""
        with httpx.Client(timeout=60.0) as client:
            filename = self._upload_image(client, portrait_path)
            log.info("uploaded %s -> %s", portrait_path, filename)
            task_id = self._create_task(client, filename, seed, prompt)
            log.info("RunningHub task %s created (workflow %s, seed %s)", task_id, self.workflow_id, seed)

            deadline = time.monotonic() + self.timeout
            while True:
                status = self._task_status(client, task_id)
                if status == "SUCCESS":
                    break
                if status in ("FAILED", "ERROR"):
                    raise RunningHubError(f"task {task_id} failed (status={status})")
                if time.monotonic() > deadline:
                    raise RunningHubError(f"task {task_id} timed out after {self.timeout}s")
                time.sleep(self.poll_interval)

            urls = self._task_outputs(client, task_id)
            log.info("task %s produced %d output(s): %s", task_id, len(urls), urls)
            return urls

    def generate(self, portrait_path: str, seed: int, style_params: dict) -> bytes:
        urls = self.run_task(portrait_path, seed, style_params.get("prompt", ""))
        if not urls:
            raise RunningHubError("task produced no outputs")
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(urls[0])
            resp.raise_for_status()
            return resp.content

    def ping(self) -> bool:
        """Lightweight reachability check of the RunningHub host."""
        try:
            with httpx.Client(timeout=3.0) as client:
                return client.get(self.base).status_code < 500
        except Exception:  # noqa: BLE001
            return False
