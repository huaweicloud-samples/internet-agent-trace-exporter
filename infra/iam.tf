# ---------------------------------------------------------------------------
# IAM 委托：函数访问 LTS（读日志）与 OBS（写备份）
# 源设计两个独立角色，华为云收敛为单个委托（触发器/转储由服务侧授权）
# ---------------------------------------------------------------------------

resource "huaweicloud_iam_agency" "exporter" {
  name                   = var.agency_name
  delegated_service_name = "op_svc_fgs"
  description            = "智能体链路导出函数委托（访问 LTS 与 OBS）。"

  project_role {
    project = var.region
    roles   = ["OBS OperateAccess", "LTS FullAccess"]
  }
}
