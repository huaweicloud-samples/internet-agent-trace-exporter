"""agent-trace-exporter 处理函数本地测试（标准库 unittest，零第三方依赖）。

运行方式：
    python3 -m unittest discover -s tests -v
或：
    python3 tests/test_handler.py
"""

import base64
import gzip
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

HANDLER_PATH = Path(__file__).resolve().parent.parent / "handler.py"


def load_handler():
    """每次重新加载模块，使环境变量变更生效（模拟不同部署配置）。"""
    spec = importlib.util.spec_from_file_location("handler", HANDLER_PATH)
    h = importlib.util.module_from_spec(spec)
    sys.modules["handler"] = h
    spec.loader.exec_module(h)
    return h


def mk_lts_event(msgs):
    """构造 LTS 触发器信封：{"lts": {"data": <base64+gzip>}}。"""
    payload = {
        "log_group_id": "demo-group",
        "log_stream_id": "demo-stream",
        "log_events": [
            {"id": str(i), "message": m} for i, m in enumerate(msgs)
        ],
    }
    data = base64.b64encode(
        gzip.compress(json.dumps(payload).encode("utf-8"))
    ).decode()
    return {"lts": {"data": data}}


SPAN_HIT = {
    "traceId": "a" * 32,
    "spanId": "b" * 16,
    "name": "hit.span",
    "kind": "INTERNAL",
    "startTimeUnixNano": "1000",
    "endTimeUnixNano": "2000",
    "attributes": {"service.name": "demo", "agent.origin": "bedrock::agent::default"},
}

SPAN_MISS = {
    "traceId": "c" * 32,
    "spanId": "d" * 16,
    "name": "miss.span",
    "kind": "CLIENT",
    "startTimeUnixNano": "1000",
    "endTimeUnixNano": "2000",
    "attributes": {"service.name": "demo", "agent.origin": "other"},
}


class TestTraceExporterHandler(unittest.TestCase):
    def setUp(self):
        os.environ["DRY_RUN"] = "true"
        os.environ["OTLP_ENCODING"] = "json"
        os.environ["FILTER_SPAN_ATTRIBUTES"] = "agent.origin=bedrock::*"
        os.environ["OTLP_ENDPOINTS"] = ""
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = ""
        os.environ["OTEL_EXPORTER_OTLP_HEADERS"] = ""

    def test_filter_hit(self):
        h = load_handler()
        r = h.handler(mk_lts_event([json.dumps(SPAN_HIT)]), None)
        self.assertEqual(r["matched"], 1)
        self.assertEqual(r["processed"], 1)

    def test_filter_miss(self):
        h = load_handler()
        r = h.handler(mk_lts_event([json.dumps(SPAN_MISS)]), None)
        self.assertEqual(r["matched"], 0)
        self.assertEqual(r["dropped"], 1)

    def test_no_filter(self):
        os.environ["FILTER_SPAN_ATTRIBUTES"] = "*"
        h = load_handler()
        r = h.handler(mk_lts_event([json.dumps(SPAN_MISS)]), None)
        self.assertEqual(r["matched"], 1)

    def test_delivery_envelope(self):
        h = load_handler()
        rec = base64.b64encode(
            gzip.compress(
                json.dumps({"logEvents": [{"message": json.dumps(SPAN_HIT)}]}).encode()
            )
        ).decode()
        r = h.handler({"records": [{"recordId": "r1", "data": rec}]}, None)
        self.assertEqual(r["matched"], 1)

    def test_direct_batch(self):
        h = load_handler()
        batch = {
            "resourceSpans": [
                {
                    "resource": {"attributes": {"service.name": "demo"}},
                    "scopeSpans": [{"spans": [SPAN_HIT]}],
                }
            ]
        }
        r = h.handler(batch, None)
        self.assertEqual(r["matched"], 1)

    def test_bad_json(self):
        h = load_handler()
        r = h.handler(mk_lts_event(["not-json"]), None)
        self.assertEqual(r["processed"], 1)
        self.assertEqual(r["matched"], 0)
        self.assertEqual(r["dropped"], 1)

    def test_no_endpoint_failure(self):
        os.environ["DRY_RUN"] = "false"
        h = load_handler()
        r = h.handler(mk_lts_event([json.dumps(SPAN_HIT)]), None)
        self.assertEqual(r["failed"], 1)

    def test_unreachable_endpoint_failure(self):
        os.environ["DRY_RUN"] = "false"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://127.0.0.1:1"
        h = load_handler()
        r = h.handler(mk_lts_event([json.dumps(SPAN_HIT)]), None)
        self.assertEqual(r["failed"], 1)

    def test_otlp_json_build(self):
        """验证 OTLP JSON 结构符合 protobuf JSON 编码约定。"""
        h = load_handler()
        payload = h.build_export_request_json([SPAN_HIT])
        self.assertIn("resourceSpans", payload)
        rs = payload["resourceSpans"][0]
        self.assertIn("resource", rs)
        self.assertIn("scopeSpans", rs)
        span = rs["scopeSpans"][0]["spans"][0]
        self.assertEqual(span["traceId"], base64.b64encode(bytes.fromhex("a" * 32)).decode())
        self.assertEqual(span["kind"], 1)  # INTERNAL
        # 无 status 字段时不得凭空生成（不缺失即可）
        self.assertNotIn("status", span)


if __name__ == "__main__":
    unittest.main(verbosity=2)
