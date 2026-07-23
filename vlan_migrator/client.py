"""Thin Prism Central v4 REST client.

Deliberately uses `requests` directly rather than the generated SDKs so the tool
has no heavyweight/per-namespace dependency chain and runs on stock Python 3.9+.
Endpoints and schemas are taken from the local v4 swagger specs:
  - networking v4.3   POST /networking/v4.3/config/$actions/migrate-subnets
  - networking v4.3   GET  /networking/v4.3/config/subnets
  - vmm         v4.0   GET  /vmm/v4.0/ahv/config/vms
  - prism       v4.3   GET  /prism/v4.3/config/tasks/{extId}
  - clustermgmt v4.0   GET  /clustermgmt/v4.0/config/clusters
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Iterator, List, Optional

import requests
import urllib3

from .config import PrismCentralConfig

# Terminal task states from prism.v4.3.config.TaskStatus.
TASK_TERMINAL = {"SUCCEEDED", "FAILED", "CANCELED"}
TASK_SUCCESS = "SUCCEEDED"


class ApiError(RuntimeError):
    """Raised for non-2xx API responses, carrying parsed error detail."""

    def __init__(self, message: str, status: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class TaskFailed(RuntimeError):
    """Raised when a tracked task reaches a non-successful terminal state."""

    def __init__(self, message: str, task: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.task = task or {}


class PrismCentralClient:
    def __init__(self, cfg: PrismCentralConfig):
        self._cfg = cfg
        self._base = f"https://{cfg.host}:{cfg.port}/api"
        self._session = requests.Session()
        self._session.auth = (cfg.username, cfg.password or "")
        self._session.headers.update(
            {"Accept": "application/json", "Content-Type": "application/json"}
        )
        if cfg.verify_ssl and cfg.ca_bundle:
            self._session.verify = cfg.ca_bundle
        else:
            self._session.verify = bool(cfg.verify_ssl)
            if not cfg.verify_ssl:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # ---- low level -----------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self._base}{path}"
        headers = dict(extra_headers or {})
        # v4 mutating actions require an idempotent NTNX-Request-Id (UUID).
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            headers.setdefault("NTNX-Request-Id", str(uuid.uuid4()))

        resp = self._session.request(
            method,
            url,
            params=params,
            json=json,
            headers=headers,
            timeout=self._cfg.timeout_secs,
        )
        if resp.status_code >= 400:
            payload = _safe_json(resp)
            raise ApiError(
                f"{method} {path} -> HTTP {resp.status_code}: {_error_text(payload)}",
                status=resp.status_code,
                payload=payload,
            )
        if resp.status_code == 204 or not resp.content:
            return {}
        return _safe_json(resp)

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        return self._request("POST", path, json=json, extra_headers=extra_headers)

    # ---- paging --------------------------------------------------------
    def get_all(
        self, path: str, params: Optional[Dict[str, Any]] = None, page_size: int = 100
    ) -> List[Dict[str, Any]]:
        """Fetch every page of a v4 list endpoint and return the merged `data`."""
        items: List[Dict[str, Any]] = []
        page = 0
        base_params = dict(params or {})
        while True:
            q = dict(base_params)
            q["$page"] = page
            q["$limit"] = page_size
            body = self.get(path, params=q)
            data = body.get("data") or []
            if isinstance(data, dict):
                data = [data]
            items.extend(data)
            if len(data) < page_size:
                break
            page += 1
        return items

    # ---- task tracking -------------------------------------------------
    def get_task(self, task_ext_id: str) -> Dict[str, Any]:
        # extId contains base64 + ':' + uuid; encode the ':' safely.
        encoded = requests.utils.quote(task_ext_id, safe="")
        return self.get(f"/prism/v4.3/config/tasks/{encoded}").get("data", {})

    def wait_for_task(
        self,
        task_ext_id: str,
        *,
        poll_interval: int = 5,
        timeout: int = 1800,
        on_progress=None,
    ) -> Dict[str, Any]:
        """Block until the task reaches a terminal state.

        Returns the final task dict on success, raises TaskFailed otherwise.
        """
        deadline = time.time() + timeout
        last_pct = -1
        while True:
            task = self.get_task(task_ext_id)
            status = task.get("status")
            pct = task.get("progressPercentage", 0)
            if on_progress and pct != last_pct:
                on_progress(status, pct)
                last_pct = pct
            if status in TASK_TERMINAL:
                if status != TASK_SUCCESS:
                    raise TaskFailed(
                        f"Task {task_ext_id} ended with status {status}: "
                        f"{_task_error_text(task)}",
                        task=task,
                    )
                return task
            if time.time() > deadline:
                raise TaskFailed(
                    f"Timed out after {timeout}s waiting for task {task_ext_id} "
                    f"(last status {status})",
                    task=task,
                )
            time.sleep(poll_interval)


def extract_task_ext_id(api_response: Dict[str, Any]) -> Optional[str]:
    """Pull the task extId from a v4 TaskReference response body."""
    data = api_response.get("data") or {}
    return data.get("extId")


def _safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        return resp.json()
    except ValueError:
        return {"_raw": resp.text}


def _error_text(payload: Any) -> str:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            errs = data.get("error") or data.get("errors")
            if errs:
                return str(errs)
        if "_raw" in payload:
            return str(payload["_raw"])[:500]
    return str(payload)[:500]


def _task_error_text(task: Dict[str, Any]) -> str:
    errs = task.get("errorMessages") or task.get("error") or []
    if errs:
        return "; ".join(
            m.get("message", str(m)) if isinstance(m, dict) else str(m) for m in errs
        )
    return task.get("operationDescription", "no error detail")
