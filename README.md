# internet-agent-trace-exporter

[![Status](https://img.shields.io/badge/Status-Incubating-blue)]()
[![Huawei Cloud](https://img.shields.io/badge/Huawei%20Cloud-Samples-red)]()
[![Scenario](https://img.shields.io/badge/Scenario-internet-success)](https://3ms.huawei.com/docs/docinfo/1300901382590492672?bookstackId=866760814559879168&gid=3591759&l=zh-cn&documentkind=&attachmentIdx=5)

This solution provides a "log → OTLP" agent trace export pipeline: the agent runtime writes trace spans as JSON to the Log Tank Service (LTS); the pipeline consumes them in real time and filters them by configurable attributes, converts matched spans to OpenTelemetry (OTLP) format, and fans them out to one or more OTLP-compatible backends (self-hosted Collector, Grafana Tempo, Jaeger, etc.), while periodically archiving raw records to Object Storage Service (OBS) with a 30-day retention period.

## Overview

This repository is created from the huaweicloud-samples automated repository request workflow.

## Getting Started

Add setup, deployment, and verification steps here.

## Contributing

Please use pull requests and follow the repository review rules.

## License

This project is licensed under the MIT-0 license.

## Maintainers

CODEOWNERS: @Ferguson2211

## Feedback

Please use GitHub Issues: https://github.com/huaweicloud-samples/internet-agent-trace-exporter/issues
