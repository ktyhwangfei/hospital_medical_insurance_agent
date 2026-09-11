# adapters/ — 外部系统防腐层

## 概述

7 个外部系统的 Ports & Adapters 实现，外加数据供给分档接入（#27）：`DataSupplyConnectionPort` 端口 + 一档 SQL Server 只读直连适配器。除数据供给一档外当前全部为内存适配器。

## 结构

```
adapters/
├── ports/                # 8 个 Protocol 接口定义
│   ├── insurance_interface.py  # InsuranceInterfacePort
│   ├── billing.py              # BillingPort
│   ├── pre_audit.py            # PreAuditPort
│   ├── drg_dip.py              # DrgDipPort
│   ├── his.py                  # HisPort
│   ├── emr.py                  # EmrPort
│   ├── medical_record.py       # MedicalRecordPort
│   └── data_supply.py          # DataSupplyConnectionPort（#27 只读连接端口）
├── base/                 # 共享基类
│   ├── models.py         # AdapterCallResult, AdapterCallContext, AdapterCallStatus
│   └── service.py        # successful_result(), failed_result(), adapter_citation()
├── insurance_interface/  # 医保接口适配器
├── billing/              # 收费系统适配器
├── pre_audit/            # 事前审核适配器
├── drg_dip/              # DRG/DIP 分组适配器
├── his/                  # HIS 系统适配器
├── emr/                  # EMR 适配器
├── medical_record/       # 病案适配器
└── data_supply/          # 数据供给适配器（#27 分档）
    └── sqlserver_direct.py    # SqlServerDirectSupplyAdapter（一档：SQL Server 只读直连）
```

## 数据供给分档（#27）

需求侧标准（跨院不变）见 `docs/steering/数据接入规范.md`；供给侧按院区分档：

- **一档**：CDR 只读视图直连（SQL Server，PEP 249 连接）— `SqlServerDirectSupplyAdapter`
- **二档**：厂商 API/中间件同步（门诊 PG 同步即此形态的产品化）
- **三档**：医保局代理 — 暂缓

约定：适配器只接受注入的 `connect_fn`（组合根在 `src/runtime/policy_qa/settlement_data_provider.py`），禁止反向 import `src.runtime`。

## 关键约定

- 所有适配器返回 `AdapterCallResult`，不抛出异常
- `DataQualityStatus`（COMPLETE/DEGRADED/MISSING）支持优雅降级
- `adapter_citation()` 生成 `Citation` 用于来源追溯
- 适配器通过 `src/config/adapters.py` 配置，支持环境变量切换实现
- 依赖注入在 `src/runtime/dependencies.py`，单例懒加载

## 场景→适配器映射

| 场景 | 使用的适配器 |
|------|-------------|
| 结算异常导办 | insurance_interface, billing |
| 出院前质控 | pre_audit, drg_dip, his, emr, medical_record |
| MCP 工具调用 | 通过 MCP 注册中心 |

## 注意事项

- 当前全部为内存实现，`P001/E001` 有数据，`P002` 触发降级
- 切换真实实现：1) 实现 Protocol 2) 设置环境变量 3) 在 dependencies.py 添加分支
