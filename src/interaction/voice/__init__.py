"""语音模块

语音采集、播放、转写处理。
"""
import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class VoiceRecord(BaseModel):
    """语音记录

    记录语音片段的元数据和转写结果。
    """

    voice_id: str = Field(..., description="语音唯一标识")
    duration: float = Field(0.0, description="语音时长（秒）")
    format: str = Field("wav", description="音频格式")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    transcript: str = Field("", description="转写文本")
    transcribed: bool = Field(False, description="是否已完成转写")


class VoiceProcessor:
    """语音处理器

    提供语音采集、播放和语音转文字能力。
    """

    def __init__(self) -> None:
        self.records: dict[str, VoiceRecord] = {}

    def capture(self, voice_id: str, duration: float = 0.0, format: str = "wav") -> VoiceRecord:
        """采集语音

        Args:
            voice_id: 语音唯一标识
            duration: 录制时长（0 表示不定长）
            format: 音频格式

        Returns:
            创建的语音记录
        """
        record = VoiceRecord(voice_id=voice_id, duration=duration, format=format)
        self.records[voice_id] = record
        logger.info("语音采集开始: %s (时长: %s)", voice_id, f"{duration}s" if duration else "不定长")
        return record

    def play(self, voice_id: str) -> bool:
        """播放语音

        Args:
            voice_id: 语音标识

        Returns:
            播放是否成功
        """
        record = self.records.get(voice_id)
        if not record:
            logger.warning("语音 %s 不存在，无法播放", voice_id)
            return False
        logger.info("播放语音: %s (时长: %ss)", voice_id, record.duration)
        return True

    def transcribe(self, voice_id: str, text: str) -> VoiceRecord | None:
        """转写语音为文本

        将语音识别结果绑定到语音记录。

        Args:
            voice_id: 语音标识
            text: 转写文本内容

        Returns:
            更新后的语音记录，不存在时返回 None
        """
        record = self.records.get(voice_id)
        if not record:
            logger.warning("语音 %s 不存在，无法转写", voice_id)
            return None
        record.transcript = text
        record.transcribed = True
        logger.info("语音转写完成: %s -> %s...", voice_id, text[:50])
        return record

    def get_record(self, voice_id: str) -> VoiceRecord | None:
        """获取语音记录

        Args:
            voice_id: 语音标识

        Returns:
            语音记录，不存在时返回 None
        """
        return self.records.get(voice_id)


# 全局语音处理器单例
voice_processor = VoiceProcessor()
