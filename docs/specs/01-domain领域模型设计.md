# domain 领域模型详细设计

## 1. 模块定位

`domain/` 是医保 AI 导办与运营协同平台的核心业务语义层，负责沉淀患者、医保、费用、审核、DRG/DIP、病案、申诉、任务等领域对象，屏蔽不同医院系统、医保专业系统和厂商接口之间的数据差异，为上下文管理、任务规划、规则解释、数据画像、业务适配和结果生成提供统一业务对象。

该模块不直接访问外部系统，不直接调用模型，不直接执行结算、审核、分组、病案修改等高风险动作，只定义业务对象、业务状态、领域规则、值对象和领域事件。

## 2. 设计目标

1. 统一平台内部医保业务语义，避免各模块直接依赖厂商字段。
2. 支撑医保结算异常导办、出院前联合质控、拒付申诉、DRG/DIP 运营、病案风险导办等场景。
3. 支撑患者医保画像、风险画像、任务闭环和审计追溯。
4. 为 `adapters/` 提供标准映射目标，为 `runtime/` 提供稳定上下文对象。
5. 为后续数据标准化、规则解释和模型提示词构造提供统一对象。

## 3. 目录结构

```text
domain/
├── patient/                 # 患者、就诊、住院、门诊
├── insurance/               # 医保待遇、医保目录、结算、清单、交易
├── order_fee/               # 医嘱、费用、药品、耗材、诊疗项目
├── audit_risk/              # 审核结果、违规风险、规则命中
├── drg_dip/                 # 病组、分组、支付、盈亏
├── medical_record/          # 病案首页、诊断、手术、编码、病历证据
├── appeal/                  # 拒付、申诉、证据、申诉材料
├── task/                    # 任务、待办、处理记录、闭环状态
└── common/                  # 通用值对象、枚举、错误码、审计对象
```

## 4. 核心领域对象

### 4.1 患者与就诊

| 对象 | 说明 | 关键字段 |
|---|---|---|
| `Patient` | 患者主对象 | `patientId`、`name`、`idNoHash`、`gender`、`birthDate` |
| `Encounter` | 一次就诊 | `encounterId`、`patientId`、`visitType`、`deptId`、`doctorId`、`status` |
| `Admission` | 住院信息 | `admissionNo`、`wardId`、`admissionDate`、`dischargeDate` |
| `PatientIdentity` | 患者身份 | `insuranceType`、`benefitType`、`insuredArea`、`specialDiseaseFlag` |

### 4.2 医保交易与结算

| 对象 | 说明 | 关键字段 |
|---|---|---|
| `InsuranceTransaction` | 医保交易流水 | `transactionId`、`businessCode`、`status`、`errorCode`、`requestTime` |
| `Settlement` | 结算结果 | `settlementId`、`totalAmount`、`fundPayAmount`、`selfPayAmount`、`status` |
| `FeeUploadStatus` | 费用上传状态 | `encounterId`、`uploadedAmount`、`failedCount`、`lastUploadTime` |
| `SettlementError` | 结算异常 | `errorCode`、`errorMessage`、`sourceSystem`、`suggestedAction` |

### 4.3 医嘱费用

| 对象 | 说明 | 关键字段 |
|---|---|---|
| `MedicalOrder` | 医嘱 | `orderId`、`orderType`、`itemCode`、`itemName`、`startTime`、`doctorId` |
| `FeeItem` | 费用明细 | `feeId`、`itemCode`、`itemName`、`amount`、`quantity`、`insuranceCategory` |
| `CatalogMapping` | 目录对码 | `hospitalCode`、`insuranceCode`、`mappingStatus`、`effectiveDate` |

### 4.4 审核风险

| 对象 | 说明 | 关键字段 |
|---|---|---|
| `AuditResult` | 事前审核结果 | `auditId`、`encounterId`、`riskLevel`、`totalRiskAmount`、`sourceSystem` |
| `RuleHit` | 规则命中 | `ruleCode`、`ruleName`、`hitReason`、`evidenceRef`、`riskAmount` |
| `ComplianceRisk` | 合规风险 | `riskType`、`riskLevel`、`responsibleRole`、`recommendedAction` |

### 4.5 DRG/DIP

| 对象 | 说明 | 关键字段 |
|---|---|---|
| `DrgDipGroupResult` | 分组结果 | `groupCode`、`groupName`、`weight`、`expectedPayAmount`、`sourceSystem` |
| `PaymentPrediction` | 支付预测 | `estimatedCost`、`expectedPay`、`profitLoss`、`riskLevel` |
| `CostStructure` | 费用结构 | `drugRatio`、`materialRatio`、`inspectionRatio`、`serviceRatio` |

### 4.6 病案与证据

| 对象 | 说明 | 关键字段 |
|---|---|---|
| `MedicalRecordHomePage` | 病案首页 | `mainDiagnosis`、`otherDiagnoses`、`surgeries`、`dischargeStatus` |
| `Diagnosis` | 诊断 | `diagnosisCode`、`diagnosisName`、`primaryFlag` |
| `Surgery` | 手术操作 | `surgeryCode`、`surgeryName`、`operationDate` |
| `EvidenceItem` | 证据项 | `evidenceType`、`sourceDocId`、`contentSummary`、`confidence` |

### 4.7 申诉与任务

| 对象 | 说明 | 关键字段 |
|---|---|---|
| `DenialCase` | 拒付病例 | `caseId`、`denialReason`、`denialAmount`、`denialDate` |
| `AppealDraft` | 申诉材料草稿 | `draftId`、`caseId`、`argumentSummary`、`evidenceRefs` |
| `GuideTask` | 导办任务 | `taskId`、`scenario`、`assigneeRole`、`priority`、`status` |
| `TaskActionRecord` | 任务处理记录 | `actionType`、`operatorId`、`beforeStatus`、`afterStatus`、`auditRef` |

## 5. 关键枚举

```text
VisitType: OUTPATIENT / INPATIENT / EMERGENCY
TaskStatus: CREATED / ASSIGNED / PROCESSING / WAIT_CONFIRM / COMPLETED / CANCELLED
RiskLevel: LOW / MEDIUM / HIGH / CRITICAL
SourceSystem: HIS / EMR / BILLING / INSURANCE_INTERFACE / PRE_AUDIT / DRG_DIP / DATA_PLATFORM
ScenarioCode: SETTLEMENT_EXCEPTION / PRE_DISCHARGE_QC / DENIAL_APPEAL / DRG_DIP_OPERATION / RECORD_RISK / POLICY_EXPLANATION
```

## 6. 领域事件

| 事件 | 触发时机 | 消费方 |
|---|---|---|
| `SettlementExceptionDetected` | 发现结算异常 | 任务规划、任务闭环、消息提醒 |
| `AuditRiskDetected` | 发现审核风险 | 出院质控、规则解释、任务闭环 |
| `DrgDipLossPredicted` | 预测病组亏损 | 科室运营、驾驶舱 |
| `AppealDraftGenerated` | 生成申诉草稿 | 医保办工作台、审计模块 |
| `GuideTaskCompleted` | 导办任务完成 | 指标体系、运营分析 |

## 7. 模块接口

```text
DomainMapper.mapFromAdapter(sourceSystem, rawData) -> DomainObject
DomainValidator.validate(domainObject) -> ValidationResult
DomainEventFactory.create(eventType, domainObject) -> DomainEvent
DomainSnapshotService.buildPatientSnapshot(patientId, encounterId) -> PatientInsuranceSnapshot
```

## 8. 边界与约束

1. 领域模型只表达业务事实、判断结果和任务状态，不直接访问数据库和外部接口。
2. 领域对象中的敏感字段默认使用脱敏值或哈希值。
3. 所有来源于外部系统的字段必须保留 `sourceSystem`、`sourceRecordId`、`dataTime`。
4. 领域模型必须支持追溯，AI 输出引用的对象必须能回查原始来源。

## 9. MVP 范围

第一期优先实现：`Patient`、`Encounter`、`InsuranceTransaction`、`Settlement`、`FeeItem`、`AuditResult`、`RuleHit`、`DrgDipGroupResult`、`MedicalRecordHomePage`、`GuideTask`。

