# 部署变量示例 —— 复制为 terraform.tfvars 后按需修改
# 注意：禁止在此文件或任何被提交的文件中写入真实凭据（C8）

region = "cn-north-4"

log_group_name = "agent-traces"
log_stream_name = "spans"

obs_bucket_name = "agent-trace-exporter-backup"

# 备份保留天数（默认 30）
backup_retention_days = 30

# span 过滤表达式；空或 "*" 表示不过滤
filter_span_attributes = "*"

# OTLP 导出编码：json（默认，零依赖）或 protobuf（需挂依赖包）
otlp_encoding = "json"

# 多端点扇出示例（逗号分隔多个对象）：
# otlp_endpoints = jsonencode([
#   { endpoint = "https://collector.example.com" },
#   { endpoint = "https://another.example.com" },
# ])
otlp_endpoints = "[]"

# 单端点兜底（otlp_endpoints 为空时生效）
otlp_endpoint = ""

# 安全默认：true 时函数仅记录不发送
dry_run = "true"

agency_name = "agent-trace-exporter-agency"

function_memory_size = 512
function_timeout = 300

# 仅 otlp_encoding = "protobuf" 时需要（构建方式见 src/tools/build-dependency.sh）
# function_dependencies = []

common_tags = {
  project = "agent-trace-exporter"
  env     = "dev"
}
