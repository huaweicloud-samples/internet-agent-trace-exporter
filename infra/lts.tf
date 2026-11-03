# ---------------------------------------------------------------------------
# 云日志服务 LTS：span 日志入口（日志组 + 日志流）
# ---------------------------------------------------------------------------

resource "huaweicloud_lts_group" "spans" {
  group_name  = var.log_group_name
  ttl_in_days = var.backup_retention_days
}

resource "huaweicloud_lts_stream" "spans" {
  group_id    = huaweicloud_lts_group.spans.id
  stream_name = var.log_stream_name
}
