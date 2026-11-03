# ---------------------------------------------------------------------------
# 对象存储服务 OBS：命中记录备份桶
# 对应源设计：私有桶 + 服务端加密 + 公网访问全封 + 30 天生命周期
# ---------------------------------------------------------------------------

resource "huaweicloud_obs_bucket" "backup" {
  bucket = var.obs_bucket_name

  # 服务端加密（AES256）
  encryption = true

  # 默认保留对象（对应源 RETAIN 策略）；测试环境可显式开启 force_destroy
  force_destroy = var.force_destroy

  storage_class = "STANDARD"

  lifecycle_rule {
    name    = "expire-traces"
    enabled = true
    prefix  = "traces/"

    expiration {
      days = var.backup_retention_days
    }
  }

  lifecycle_rule {
    name    = "expire-errors"
    enabled = true
    prefix  = "errors/"

    expiration {
      days = var.backup_retention_days
    }
  }

  tags = var.common_tags
}

# 说明：源设计含 Block Public Access（公网访问全封）。OBS 对应能力为「桶级阻止公共访问
# 配置」（PUT /?publicAccessBlock），实测 cn-north-4 该特性未开启（405 MethodNotAllowed，
# 官方错误码语义=特性开关未开启）。OBS 新建对象桶默认私有（ACL private），本资源已移除，
# 桶的私密性由默认 ACL 保证；如需该增强防护，可在支持区域（新区域/特性开启后）补回。
