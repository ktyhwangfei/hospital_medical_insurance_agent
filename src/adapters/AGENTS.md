# adapters/ — 外部系统防腐层

## 概述

7 个外部系统的 Ports & Adapters 实现。当前全部为内存适配器。

## 结构

```
adapters/
├── ports/                # 7 个 Protocol 接口定义
│   ├── insurance_interface.py  # InsuranceInterfacePort
│   ├── billing.py              # BillingPort
│   ├── pre_audit.py            # PreAuditPort
│   ├── drg_dip.py              # DrgDipPort
│   ├── his.py                  # HisPort
│   ├── emr.py                  # EmrPort
│   └── medical_record.py       # MedicalRecordPort
├── base/                 # 共享基类
│   ├── models.py         # AdapterCallResult, AdapterCallContext, AdapterCallStatus
│   └── service.py        # successful_result(), failed_result(), adapter_citation()
├── insurance_interface/  # 医保接口适配器
├── billing/              # 收费系统适配器
├── pre_audit/            # 事前审核适配器
├── drg_dip/              # DRG/DIP 分组适配器
├── his/                  # HIS 系统适配器
├── emr/                  # EMR 适配器
└── medical_record/       # 病案适配器
```

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
