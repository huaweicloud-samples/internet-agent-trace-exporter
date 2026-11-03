variable "region" {
  description = "华为云部署区域。"
  type        = string
  default     = "cn-north-4"
}

variable "log_group_name" {
  description = "LTS 日志组名称，智能体运行时将 span 写入该日志组。"
  type        = string
  default     = "agent-traces"
}

variable "log_stream_name" {
  description = "LTS 日志流名称，函数订阅该日志流。"
  type        = string
  default     = "spans"
}

variable "obs_bucket_name" {
  description = "OBS 备份桶名称（需全局唯一）。"
  type        = string
  default     = "agent-trace-exporter-backup"
}

variable "backup_retention_days" {
  description = "备份对象过期天数（对应源设计 30 天备份）。"
  type        = number
  default     = 30
}

variable "force_destroy" {
  description = "为 true 时销毁允许清空桶内对象（仅测试环境建议开启）。"
  type        = bool
  default     = false
}

variable "filter_span_attributes" {
  description = "span 属性过滤表达式；空或 '*' 表示不过滤。格式：key=v1|v2,key2=v3（尾缀 '*' 为前缀匹配）。"
  type        = string
  default     = "*"
}

variable "otlp_encoding" {
  description = "OTLP 导出编码：json（默认，零依赖）或 protobuf（需挂依赖包）。"
  type        = string
  default     = "json"

  validation {
    condition     = contains(["json", "protobuf"], var.otlp_encoding)
    error_message = "otlp_encoding 取值必须为 json 或 protobuf。"
  }
}

variable "otlp_endpoints" {
  description = "OTLP 端点 JSON 数组，支持多端点扇出，如 [{\"endpoint\":\"https://collector.example.com\"}]。"
  type        = string
  default     = "[]"
}

variable "otlp_endpoint" {
  description = "单个 OTLP 端点 URL（otlp_endpoints 为空时的兜底）。"
  type        = string
  default     = ""
}

variable "dry_run" {
  description = "为 true 时函数仅记录输入输出、不真正发送到 OTLP（默认 true，安全起见）。"
  type        = string
  default     = "true"
}

variable "agency_name" {
  description = "函数委托名称（访问 LTS / OBS）。"
  type        = string
  default     = "agent-trace-exporter-agency"
}

variable "function_memory_size" {
  description = "FunctionGraph 函数内存（MB）。"
  type        = number
  default     = 512
}

variable "function_timeout" {
  description = "FunctionGraph 函数超时（秒）。"
  type        = number
  default     = 300
}

variable "function_dependencies" {
  description = "FunctionGraph 依赖包 ID 列表（仅 otlp_encoding = protobuf 时需要）。"
  type        = list(string)
  default     = []
}

variable "common_tags" {
  description = "应用到可打标资源的标签。"
  type        = map(string)
  default     = {}
}
