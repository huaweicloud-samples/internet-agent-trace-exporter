# ---------------------------------------------------------------------------
# FunctionGraph：处理函数（等价源仓库的处理函数）
#  - 内联代码交付（默认 JSON 编码零依赖，无需构建/上传依赖包）
#  - 配置经 user_data 注入（非敏感），敏感项经加密字段注入（仅占位符）
#  - 运行期轮换的加密配置由 ignore_changes 让出所有权（C10）
# ---------------------------------------------------------------------------

resource "huaweicloud_fgs_function" "exporter" {
  name        = "agent-trace-exporter"
  app         = "default"
  runtime     = "Python3.10"
  handler     = "handler.handler"
  memory_size = var.function_memory_size
  timeout     = var.function_timeout
  description = "按属性过滤智能体链路 span 并导出到 OTLP 兼容后端。"

  # 显式指定内联代码模式：provider 1.97 不设置时请求体缺 code_type，
  # 服务端报 FSS.1006 "Invalid code type"（实测）
  code_type = "inline"

  # 委托绑定：LTS 触发器必需（无 xrole 报 FSS.1020 "invalid xrole"）。
  # ⚠️ FSS.1501 阻塞：子账号缺少域级 iam:agencies:get 权限，FunctionGraph
  # 内部查委托被拒（详见 docs/deployment-verification-report.md §6）。
  # 部署验证期间临时注释，待 IAM 管理员补权后恢复下行：
  # agency = huaweicloud_iam_agency.exporter.name

  # 内联源码（标准库实现，OTLP JSON 编码）
  func_code = file("${path.module}/../src/functions/exporter/handler.py")

  # 非敏感配置（注入为环境变量）
  # 注意：cn-north-4 实测 user_data 必须为 JSON 对象格式（{"KEY":"VALUE"}），
  #       provider 默认的 KEY=VALUE 换行格式会触发 FSS.1009 "Invalid environment variable"；
  #       且环境变量值不允许为空字符串（空值同样 FSS.1009），故 otlp_endpoint 未配置时剔除该键。
  #       服务端展开为环境变量后由 handler 经 os.getenv 读取。
  user_data = jsonencode(merge(
    {
      DRY_RUN                = var.dry_run
      OTLP_ENCODING          = var.otlp_encoding
      FILTER_SPAN_ATTRIBUTES = var.filter_span_attributes
      OTLP_ENDPOINTS         = var.otlp_endpoints
    },
    var.otlp_endpoint == "" ? {} : { OTEL_EXPORTER_OTLP_ENDPOINT = var.otlp_endpoint },
  ))

  # 敏感配置（加密存储，仅占位符，部署时替换为真实值；禁止提交真实凭据，见 C8）
  # 同样必须为 JSON 对象格式
  encrypted_user_data = jsonencode({
    OTEL_EXPORTER_OTLP_HEADERS = "<OTLP_HEADERS>"
  })

  # 仅 protobuf 编码时需要依赖包
  depend_list = var.function_dependencies

  lifecycle {
    # 端点头部信息（加密字段）由运维在运行期轮换；Terraform 不得回滚（C10）
    ignore_changes = [encrypted_user_data]
  }
}

# ---------------------------------------------------------------------------
# FunctionGraph LTS 触发器：等价源「日志订阅过滤器」（全事件实时投递）
# ---------------------------------------------------------------------------

resource "huaweicloud_fgs_trigger" "lts" {
  function_urn = huaweicloud_fgs_function.exporter.urn
  type         = "LTS"

  lts {
    log_group_id = huaweicloud_lts_group.spans.id
    log_topic_id = huaweicloud_lts_stream.spans.id
  }

  lifecycle {
    # 运维可临时停用触发器止损；Terraform 不得在下次 apply 重新启用（C10）
    ignore_changes = [status]
  }
}
