# 部署指导书 —— 智能体链路导出器（agent-trace-exporter）

> 华为云实践文档。面向中国客户，指导在华为云完成本方案的部署、验证与清理。

---

## 1. 前置条件

| 项 | 说明 |
|---|---|
| 华为云账号 | 具备 LTS、FunctionGraph、OBS、IAM 的创建权限；**且具备域级 IAM 委托查询权限（`iam:agencies:get`）**——否则函数 xrole 绑定与 LTS 触发器创建将失败（FSS.1501，详见部署验证报告 §6） |
| 区域 | 默认 `cn-north-4`（华北-北京四），可在 `terraform.tfvars` 调整 |
| 工具 | Terraform ≥ 1.5，`huaweicloud` provider ≥ 1.97（离线插件目录见 `infra/README.md`） |
| 凭据 | 环境变量注入：`HW_ACCESS_KEY` / `HW_SECRET_KEY`（仅注入运行期临时环境变量，不落盘、不提交） |
| OTLP 端点 | 一个或多个 OTLP 兼容后端地址（自建 Collector / Tempo / Jaeger 等） |

> ⚠️ 首次部署建议保持 `dry_run="true"`，确认链路通畅后再关闭。

---

## 2. 部署步骤

### 步骤 1：准备变量

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
# 编辑 terraform.tfvars：设置 obs_bucket_name（需全局唯一）、
# 按需设置 filter_span_attributes / otlp_endpoints / dry_run 等
```

### 步骤 2：初始化与校验

```bash
terraform init -backend=false -plugin-dir=<plugin-cache目录>
terraform fmt -check -recursive
terraform validate
```

预期输出：`Success! The configuration is valid.`

### 步骤 3：查看执行计划

```bash
terraform plan
```

预期输出：8 个资源待创建（LTS 组/流、函数、触发器、转储、OBS 桶、BPA、委托）。

### 步骤 4：应用部署

```bash
terraform apply
```

预期输出：`Apply complete!`，并输出 `function_urn`、`log_group_id`、`log_stream_id`、`obs_backup_bucket`。

### 步骤 5：配置 OTLP 端点头部（可选）

若 OTLP 后端需要鉴权头（如 API Key）：

1. 在 FunctionGraph 控制台打开函数 `agent-trace-exporter` →「配置」→「环境变量」。
2. 在加密环境变量中更新 `OTEL_EXPORTER_OTLP_HEADERS`（如 `Authorization=Bearer <TOKEN>`）。
3. 保存后触发器自动生效（Terraform 不会回滚该字段，见 C10）。

---

## 3. 接入智能体链路

智能体运行时 / 框架将 span 以 JSON 写入 LTS 日志流 `agent-traces/spans`（每行一条，支持两种格式）：

- **单 span**：顶层含 `traceId` / `spanId` / `name` / `attributes` 等字段的 JSON 对象。
- **OTLP 批次**：含 `resourceSpans` 的 OTLP JSON 结构。

示例（单 span）：

```json
{
  "traceId": "0af7651916cd43dd8448eb211c80319c",
  "spanId": "b7ad6b7169203331",
  "name": "agent.plan",
  "kind": "INTERNAL",
  "startTimeUnixNano": "1544712660000000000",
  "endTimeUnixNano": "1544712661000000000",
  "attributes": {
    "service.name": "demo-agent",
    "agent.origin": "sample.agent.runtime"
  }
}
```

写入方式不限：日志 SDK、直接写 LTS API，或通过其他采集通道汇入该日志流。

---

## 4. 验证

### 4.1 函数逻辑本地验证（离线）

```bash
cd src/functions/exporter
python3 -m unittest discover -s tests -v
```

预期输出：`Ran 9 tests ... OK`。

### 4.2 端到端验证（云端）

1. **确认 dry_run 已关闭**（`dry_run="false"`）。
2. 向 LTS 日志流写入一条测试 span（可用 `src/samples/sample_span.py` 生成）。
3. 打开 FunctionGraph 控制台 → 函数 `agent-trace-exporter` →「日志」，观察：
   - `Exporting N spans` 与 `Exported M resource spans (K bytes) to <endpoint>`。
   - 返回摘要 `{"processed": 1, "matched": 1, "dropped": 0, "failed": 0}`。
4. 在 OTLP 后端查询该 trace 是否到达。
5. **备份验证**：等待 2–5 分钟，检查 OBS 桶 `traces/` 前缀下出现按时间分目录的归档对象。

### 4.3 过滤验证（可选）

- 设 `filter_span_attributes="agent.origin=sample.agent.*"`，写入 `agent.origin=sample.agent.runtime` 的 span → 应匹配导出；
- 写入 `agent.origin=other` 的 span → 应被丢弃（摘要 `matched` 不增加）。

---

## 5. 清理

```bash
cd infra
terraform destroy
```

> ⚠️ 默认 `force_destroy=false`：若 OBS 桶中仍有归档对象，销毁会失败（保护数据）。
> 确认不再需要备份数据后，再显式删除桶内对象或开启 `force_destroy=true` 后销毁。

---

## 6. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 摘要 `failed: 1` | 无端点配置 / 端点不可达 | 检查 `otlp_endpoints`/`otlp_endpoint`；确认网络可达 |
| 函数日志无触发记录 | 日志流无新事件 / 触发器停用 | 检查写入路径；查看触发器状态 |
| `matched: 0` | 过滤条件未命中 | 调整 `filter_span_attributes` 或置 `*` |
| OBS 无归档 | 转储任务未启 / 周期未到 | 检查转储状态；等待 2min 周期；确认委托权限 |
| 密钥相关报错 | 端点头部配置错误 | 检查加密环境变量 `OTEL_EXPORTER_OTLP_HEADERS` |
