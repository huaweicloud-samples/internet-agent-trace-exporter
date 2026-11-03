#!/usr/bin/env bash
# 构建 FunctionGraph 依赖包（仅 otlp_encoding = "protobuf" 时需要）。
#
# 用法:
#   bash build-dependency.sh [输出目录]
#
# 产物: 一个 zip 包，包含 opentelemetry-proto + protobuf 及其依赖，
# 上传到 FunctionGraph 控制台「依赖管理」后，将返回的依赖 ID 填入
# infra 的 function_dependencies 变量。
#
# 默认编码为 json（零依赖），无需运行本脚本。

set -euo pipefail

OUT_DIR="${1:-dist}"
REQ_FILE="$(dirname "$0")/../functions/exporter/requirements.txt"

if [[ ! -f "$REQ_FILE" ]]; then
  echo "未找到依赖清单: $REQ_FILE" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
python3 -m venv "$OUT_DIR/venv"
# shellcheck disable=SC1091
source "$OUT_DIR/venv/bin/activate"
pip install -q -r "$REQ_FILE" -t "$OUT_DIR/package"
cd "$OUT_DIR/package"
zip -qr "../opentelemetry-deps.zip" .
cd - >/dev/null
deactivate

echo "依赖包已生成: $OUT_DIR/opentelemetry-deps.zip"
echo "请到 FunctionGraph 控制台创建依赖（Python3.10），"
echo "并将依赖 ID 填入 infra/terraform.tfvars 的 function_dependencies。"
