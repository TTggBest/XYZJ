import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

EXECUTOR_PROTOCOL = 3


class CloudConflict(RuntimeError):
    pass


class CloudNotFound(RuntimeError):
    pass


class CloudClient:
    def __init__(self, base_url, session_token, host_id, tenant_id):
        url = urlparse(base_url)
        if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"}):
            raise ValueError("云端连接必须使用 HTTPS；HTTP 仅允许本机测试")
        self.base_url, self.token = base_url.rstrip("/"), session_token
        self.host_id, self.tenant_id = host_id, tenant_id

    def request(self, method, path, body=None, *, timeout=20):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base_url + "/api/v3" + path, data=data, method=method,
            headers={"Cookie": "zhiju_session=" + self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return None if response.status == 204 else json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise PermissionError("智矩登录已失效、公司已切换或主机绑定不匹配，请重新登录配置") from None
            if exc.code == 404:
                raise CloudNotFound("云端请求失败 HTTP 404") from None
            if exc.code == 409:
                error = json.load(exc).get("detail", "执行状态冲突")
                raise CloudConflict(str(error)) from None
            raise RuntimeError(f"云端请求失败 HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ConnectionError("无法连接智矩；保留本地待回传结果") from exc

    def claim(self):
        principal = self.request("GET", "/auth/me")
        if principal["tenant_id"] != self.tenant_id:
            raise PermissionError("当前会话公司已切换；停止领取")
        result = self.request("POST", "/v14/claims", {"host_id": self.host_id, "executor_protocol": EXECUTOR_PROTOCOL})
        if result and result["tenant_id"] != self.tenant_id:
            raise PermissionError("领取结果不属于本机配置的公司")
        return result

    def begin(self, envelope, node):
        result = self.request("POST", f"/v14/runs/{envelope['run_id']}/attempts",
            {"claim_id": envelope["claim_id"], "node_type": node})
        if 'planning_context' in result:
            envelope.update(result['planning_context'])
        return result['attempt_id']

    def current(self, envelope):
        return self.request("GET", f"/work-orders/{envelope['work_order_id']}/v14-runs/current")

    def submit(self, envelope, attempt, body):
        return self.request("PUT", f"/v14/runs/{envelope['run_id']}/attempts/{attempt}", body)

    def heartbeat(self, envelope):
        return self.request("POST", f"/v14/runs/{envelope['run_id']}/heartbeat", {"claim_id": envelope["claim_id"]})

    def download_analysis_material(self, run_id, material_id):
        request = urllib.request.Request(self.base_url + f'/api/v3/analysis-runs/{run_id}/materials/{material_id}',
            headers={'Cookie':'zhiju_session='+self.token})
        try:
            with urllib.request.urlopen(request,timeout=60) as response:
                return response.read(32*1024*1024+1)
        except urllib.error.HTTPError as exc:
            if exc.code in {401,403}:raise PermissionError('分析素材授权失效') from None
            raise RuntimeError(f'分析素材下载失败 HTTP {exc.code}') from None
        except (urllib.error.URLError, TimeoutError):
            raise ConnectionError('分析素材下载失败') from None
