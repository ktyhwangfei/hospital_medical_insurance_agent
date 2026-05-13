"""知识上传模块

政策文件、制度文档、规则说明等知识资产的导入管理。
"""
import logging
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class KnowledgeType(str, Enum):
    """知识类型枚举"""
    POLICY = "policy"                      # 医保政策
    REGULATION = "regulation"              # 医院制度
    RULE = "rule"                          # 业务规则
    GUIDELINE = "guideline"                # 操作指南
    REFERENCE = "reference"                # 参考资料


class KnowledgeStatus(str, Enum):
    """知识状态"""
    PENDING = "pending"           # 待处理
    PROCESSING = "processing"     # 处理中
    INDEXED = "indexed"           # 已索引
    FAILED = "failed"             # 处理失败


class KnowledgeDocument(BaseModel):
    """知识文档

    表示一条导入的知识资产，包含内容、类型、状态等元信息。
    """

    doc_id: str = Field(..., description="文档唯一标识")
    title: str = Field(..., description="文档标题")
    content: str = Field(..., description="文档内容")
    type: KnowledgeType = Field(KnowledgeType.POLICY, description="知识类型")
    status: KnowledgeStatus = Field(KnowledgeStatus.PENDING, description="处理状态")
    source: str = Field("", description="来源说明")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    uploaded_by: str = Field("", description="上传者")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")


class KnowledgeUploader:
    """知识上传器

    处理医保政策、医院制度、业务规则等知识文档的导入和管理。
    """

    def __init__(self) -> None:
        self.documents: dict[str, KnowledgeDocument] = {}

    def upload(
        self,
        doc_id: str,
        title: str,
        content: str,
        type: KnowledgeType = KnowledgeType.POLICY,
        source: str = "",
        tags: list[str] | None = None,
        uploaded_by: str = "",
    ) -> KnowledgeDocument:
        """上传知识文档

        Args:
            doc_id: 文档唯一标识
            title: 文档标题
            content: 文档内容
            type: 知识类型
            source: 来源说明
            tags: 标签列表
            uploaded_by: 上传者

        Returns:
            创建的知识文档
        """
        document = KnowledgeDocument(
            doc_id=doc_id,
            title=title,
            content=content,
            type=type,
            source=source,
            tags=tags or [],
            uploaded_by=uploaded_by,
        )
        self.documents[doc_id] = document
        logger.info(
            "知识文档上传: [%s] %s (上传者: %s)", type.value, title, uploaded_by,
        )
        return document

    def index(self, doc_id: str) -> bool:
        """标记文档为已索引（模拟向量化入库）

        Args:
            doc_id: 文档标识

        Returns:
            操作是否成功
        """
        document = self.documents.get(doc_id)
        if not document:
            logger.warning("文档 %s 不存在，无法索引", doc_id)
            return False
        document.status = KnowledgeStatus.INDEXED
        document.updated_at = datetime.now()
        logger.info("知识文档已索引: %s", doc_id)
        return True

    def get_document(self, doc_id: str) -> KnowledgeDocument | None:
        """获取知识文档

        Args:
            doc_id: 文档标识

        Returns:
            知识文档，不存在时返回 None
        """
        return self.documents.get(doc_id)

    def search_by_type(self, type: KnowledgeType) -> list[KnowledgeDocument]:
        """按类型查询知识文档

        Args:
            type: 知识类型

        Returns:
            匹配的文档列表
        """
        return [doc for doc in self.documents.values() if doc.type == type]

    def search_by_tags(self, tags: list[str]) -> list[KnowledgeDocument]:
        """按标签查询知识文档

        Args:
            tags: 标签列表

        Returns:
            匹配的文档列表（至少匹配一个标签）
        """
        tag_set = set(tags)
        return [
            doc for doc in self.documents.values()
            if tag_set & set(doc.tags)
        ]


# 全局知识上传器单例
knowledge_uploader = KnowledgeUploader()
