output "region" {
  description = "部署区域。"
  value       = var.region
}

output "function_urn" {
  description = "导出函数 URN。"
  value       = huaweicloud_fgs_function.exporter.urn
}

output "log_group_id" {
  description = "智能体写入 span 的 LTS 日志组 ID。"
  value       = huaweicloud_lts_group.spans.id
}

output "log_stream_id" {
  description = "函数订阅的 LTS 日志流 ID。"
  value       = huaweicloud_lts_stream.spans.id
}

output "obs_backup_bucket" {
  description = "备份 OBS 桶名称（traces/ 前缀，30 天过期）。"
  value       = huaweicloud_obs_bucket.backup.bucket
}
