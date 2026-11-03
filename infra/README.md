# infra —— 基础设施（Terraform + huaweicloud provider）

智能体链路导出器的华为云基础设施定义。全部资源以 Terraform 声明，无其他 IaC 框架混用。

## 资源清单

| 文件 | 资源 | 说明 |
|---|---|---|
| `lts.tf` | LTS 日志组 + 日志流 | 智能体 span 写入入口 |
| `function.tf` | FunctionGraph 函数 + LTS 触发器 | 处理函数（内联代码）+ 实时订阅 |
| `transfer.tf` | LTS 转储任务 | 周期归档到 OBS（2min） |
| `obs.tf` | OBS 备份桶 + 公网封禁 | AES256 加密、私有、30 天生命周期 |
| `iam.tf` | IAM 委托 | 函数读 LTS + 写 OBS |
| `variables.tf` / `outputs.tf` | 变量与输出 | 配置入口与部署结果 |

## 使用

```bash
terraform init -backend=false -plugin-dir=<离线插件缓存目录>
terraform fmt -check -recursive
terraform validate
terraform plan
terraform apply
```

凭据经环境变量注入运行期临时环境（不落盘、不提交）；端点头部等敏感配置仅占位符，部署后在控制台以加密字段更新。

## 费用

全部按用量计费（FunctionGraph 按调用、LTS 按日志量、OBS 按存储），无固定规格资源，闲置 ≈ ¥0/月；不使用时 `terraform destroy` 清理。
