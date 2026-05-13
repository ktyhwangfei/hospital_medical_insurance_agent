"""文件上传模块

文件上传、预览、引用管理。
"""
import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class FileRecord(BaseModel):
    """文件记录

    记录已上传文件的元数据信息。
    """

    file_id: str = Field(..., description="文件唯一标识")
    filename: str = Field(..., description="原始文件名")
    file_size: int = Field(..., description="文件大小（字节）")
    mime_type: str = Field(..., description="MIME 类型")
    upload_time: datetime = Field(default_factory=datetime.now, description="上传时间")
    storage_path: str = Field("", description="存储路径")
    uploaded_by: str = Field("", description="上传者")


class FileUploader:
    """文件上传器

    处理文件上传、预览生成、文件引用等操作。
    """

    def __init__(self) -> None:
        self.files: dict[str, FileRecord] = {}
        # 允许的文件类型
        self.allowed_types: set[str] = {
            "image/jpeg", "image/png", "image/gif",
            "application/pdf",
            "text/plain", "text/csv",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

    def upload(self, file_id: str, filename: str, file_size: int, mime_type: str,
               uploaded_by: str = "", storage_path: str = "") -> FileRecord | None:
        """上传文件（记录元信息）

        Args:
            file_id: 文件唯一标识
            filename: 原始文件名
            file_size: 文件大小
            mime_type: MIME 类型
            uploaded_by: 上传者
            storage_path: 存储路径

        Returns:
            文件记录，类型不允许时返回 None
        """
        if mime_type not in self.allowed_types:
            logger.warning("不支持的文件类型: %s", mime_type)
            return None

        record = FileRecord(
            file_id=file_id,
            filename=filename,
            file_size=file_size,
            mime_type=mime_type,
            uploaded_by=uploaded_by,
            storage_path=storage_path,
        )
        self.files[file_id] = record
        logger.info("文件上传成功: %s (%s, %d bytes)", filename, mime_type, file_size)
        return record

    def preview(self, file_id: str) -> dict[str, Any] | None:
        """获取文件预览信息

        Args:
            file_id: 文件标识

        Returns:
            预览信息字典，文件不存在时返回 None
        """
        record = self.files.get(file_id)
        if not record:
            logger.warning("文件 %s 不存在", file_id)
            return None
        return {
            "file_id": record.file_id,
            "filename": record.filename,
            "mime_type": record.mime_type,
            "file_size": record.file_size,
            "upload_time": record.upload_time.isoformat(),
            "preview_url": f"/api/v1/files/{record.file_id}/preview",
        }

    def reference(self, file_id: str) -> str:
        """生成文件引用标记

        Args:
            file_id: 文件标识

        Returns:
            引用标记字符串
        """
        return f"【文件引用: {file_id}】"

    def get_file(self, file_id: str) -> FileRecord | None:
        """获取文件记录

        Args:
            file_id: 文件标识

        Returns:
            文件记录，不存在时返回 None
        """
        return self.files.get(file_id)


# 全局文件上传器单例
file_uploader = FileUploader()
