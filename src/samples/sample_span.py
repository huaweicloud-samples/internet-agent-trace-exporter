"""示例智能体 span（JSON）—— 用于本地调试 / 手工验证处理函数。

用法：
    python3 sample_span.py > span.json
    # 然后可直接 POST 到函数入口做直连验证：
    # curl -X POST <函数URL> -H 'Content-Type: application/json' --data @span.json
"""

import json


def sample_span() -> dict:
    """构造一条含智能体 origin 属性的示例 span（OTLP JSON 结构）。"""
    return {
        "traceId": "0af7651916cd43dd8448eb211c80319c",
        "spanId": "b7ad6b7169203331",
        "parentSpanId": "",
        "name": "agent.plan",
        "kind": "INTERNAL",
        "startTimeUnixNano": "1544712660000000000",
        "endTimeUnixNano": "1544712661000000000",
        "attributes": {
            "service.name": "demo-agent",
            "agent.origin": "sample.agent.runtime",
            "gen_ai.request.model": "demo-model",
        },
        "status": {"code": "OK", "message": ""},
        "flags": 1,
    }


if __name__ == "__main__":
    print(json.dumps(sample_span(), indent=2, ensure_ascii=False))
