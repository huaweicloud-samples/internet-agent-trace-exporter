# ---------------------------------------------------------------------------
# LTS 转储任务：等价源投递流「缓冲 + 压缩 + 时间分区归档」到 OBS
# 周期（默认 2 分钟）将 span 日志流归档到备份桶 traces/ 前缀
# ---------------------------------------------------------------------------

# 目标桶已开启 SSE-KMS 加密（默认密钥 kps/default）；LTS 转储到加密桶时
# 必须显式携带桶的加密密钥 ID，否则报 LTS.2102 kms key id verify error。
data "huaweicloud_kms_key" "obs_encryption" {
  key_alias = "kps/default"
}

resource "huaweicloud_lts_transfer" "obs_backup" {
  log_group_id = huaweicloud_lts_group.spans.id

  log_streams {
    log_stream_id = huaweicloud_lts_stream.spans.id
  }

  log_transfer_info {
    log_transfer_type   = "OBS"
    log_transfer_mode   = "cycle"
    log_transfer_status = "ENABLE"
    log_storage_format  = "RAW"

    log_transfer_detail {
      obs_bucket_name      = huaweicloud_obs_bucket.backup.bucket
      obs_dir_prefix_name  = "traces/"
      obs_period           = 2
      obs_period_unit      = "min"
      obs_transfer_path    = "/"
      obs_encrypted_enable = true
      obs_encrypted_id     = data.huaweicloud_kms_key.obs_encryption.id
    }
  }

  lifecycle {
    # 转储任务可在控制台暂停/恢复；Terraform 不得在下次 apply 回滚（C10）
    ignore_changes = [log_transfer_info[0].log_transfer_status]
  }
}
