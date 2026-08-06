"""Skill 导入服务（P3）。

支持三种导入来源（设计 §4.2）：ZIP 上传、受控服务器目录、Git 地址。
导入只生成独立草稿，不写入正式 ``skills/``，也不执行其中脚本（设计 §8.2）。

安全校验（设计 §8.2）：
- ZIP：大小/数量/扩展名白名单、目录穿越、符号链接
- Git：协议与主机白名单、禁止本机/内网/保留地址
- 受控目录：限制在配置的导入根目录
- 内容扫描：复用 P2 校验器的敏感内容检测
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.config.production import SKILLS_DIR
from src.domain.skill.draft_models import (
    SkillDraft,
    SkillDraftSourceType,
)
from src.runtime.skill_management.draft_service import SkillDraftService
from src.runtime.skill_management.draft_validator import SkillDraftValidator

# 导入安全限制（设计 §8.2）
MAX_ZIP_BYTES = 50 * 1024 * 1024  # 50MB
MAX_ZIP_FILES = 500
ALLOWED_EXTENSIONS = frozenset(
    {
        ".yaml", ".yml", ".json", ".md", ".py", ".txt",
        ".csv", ".html", ".js", ".ts", ".tsx",
    }
)
_ALLOWED_GIT_PROTOCOLS = {"https", "ssh", "git"}
_BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost")
_BLOCKED_HOST_LITERALS = {"localhost", "0.0.0.0", "::1"}
_PRIVATE_IP_PREFIXES = ("10.", "172.16.", "172.17.", "172.18.", "172.19.",
                        "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                        "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                        "172.30.", "172.31.", "192.168.", "127.")


class SkillImportError(ValueError):
    """导入安全校验失败。"""


class SkillImportService:
    def __init__(
        self,
        draft_service: SkillDraftService,
        *,
        validator: SkillDraftValidator | None = None,
        import_root: str | Path | None = None,
    ) -> None:
        self._draft_service = draft_service
        self._validator = validator or SkillDraftValidator()
        self._import_root = (
            Path(import_root)
            if import_root is not None
            else Path(os.getenv("SKILL_IMPORT_ROOT", "") or "").resolve()
            if os.getenv("SKILL_IMPORT_ROOT")
            else None
        )

    # ── ZIP 导入 ──────────────────────────────────────────────────

    def import_from_zip(
        self,
        *,
        upload_bytes: bytes,
        filename: str,
        created_by: str,
    ) -> SkillDraft:
        if len(upload_bytes) > MAX_ZIP_BYTES:
            raise SkillImportError(
                f"ZIP 超过大小上限 {MAX_ZIP_BYTES} 字节"
            )
        files = self._extract_zip(upload_bytes)
        self._validate_extension_whitelist(files)
        self._validate_content_safety(files)
        return self._create_import_draft(
            files=files,
            source_label=filename,
            created_by=created_by,
        )

    def _extract_zip(self, upload_bytes: bytes) -> dict[str, str]:
        files: dict[str, str] = {}
        try:
            zf = zipfile.ZipFile(io.BytesIO(upload_bytes))
        except zipfile.BadZipFile as exc:
            raise SkillImportError("不是合法的 ZIP 文件") from exc
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_ZIP_FILES:
            raise SkillImportError(
                f"ZIP 文件数量超过上限 {MAX_ZIP_FILES}"
            )
        for info in infos:
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts:
                raise SkillImportError(f"ZIP 包含非法路径: {name}")
            # 符号链接检测（Unix 属性位）
            if _is_symlink_attr(info.external_attr):
                raise SkillImportError(f"ZIP 包含符号链接: {name}")
            if info.file_size > MAX_ZIP_BYTES:
                raise SkillImportError(f"ZIP 内文件过大: {name}")
            try:
                content = zf.read(info).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SkillImportError(
                    f"文件 {name} 不是 UTF-8 文本"
                ) from exc
            # 归一化到相对路径，去掉顶层目录前缀（Skill 包根目录）
            relative = _strip_top_level_dir(name)
            files[relative] = content
        if not files:
            raise SkillImportError("ZIP 不包含任何文件")
        return files

    # ── 受控目录导入 ──────────────────────────────────────────────

    def import_from_controlled_dir(
        self,
        *,
        relative_path: str,
        created_by: str,
    ) -> SkillDraft:
        if self._import_root is None:
            raise SkillImportError("受控目录导入未配置 SKILL_IMPORT_ROOT")
        target = (self._import_root / relative_path).resolve()
        # 禁止 .. 跳出导入根目录
        try:
            target.relative_to(self._import_root)
        except ValueError as exc:
            raise SkillImportError(
                f"路径越界，必须在导入根目录内: {relative_path}"
            ) from exc
        if not target.exists() or not target.is_dir():
            raise SkillImportError(f"导入目录不存在: {relative_path}")
        files = self._read_directory(target)
        if not files:
            raise SkillImportError(f"目录为空: {relative_path}")
        self._validate_extension_whitelist(files)
        self._validate_content_safety(files)
        return self._create_import_draft(
            files=files,
            source_label=str(relative_path),
            created_by=created_by,
        )

    def _read_directory(self, target: Path) -> dict[str, str]:
        files: dict[str, str] = {}
        for path in target.rglob("*"):
            if not path.is_file():
                continue
            if path.is_symlink():
                raise SkillImportError(f"受控目录含符号链接: {path}")
            if path.stat().st_size > MAX_ZIP_BYTES:
                raise SkillImportError(f"文件过大: {path.name}")
            rel = path.relative_to(target).as_posix()
            try:
                files[rel] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise SkillImportError(
                    f"文件 {rel} 不是 UTF-8 文本"
                ) from exc
        return files

    # ── Git 导入 ──────────────────────────────────────────────────

    def import_from_git(
        self,
        *,
        url: str,
        created_by: str,
    ) -> SkillDraft:
        self._validate_git_url(url)
        tmp = Path(tempfile.mkdtemp(prefix="skill-import-git-"))
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", url, str(tmp)],
                check=True,
                capture_output=True,
                timeout=120,
            )
            files = self._read_directory(tmp)
            if not files:
                raise SkillImportError("Git 仓库不包含任何文件")
            self._validate_extension_whitelist(files)
            self._validate_content_safety(files)
            return self._create_import_draft(
                files=files, source_label=url, created_by=created_by
            )
        except FileNotFoundError as exc:
            raise SkillImportError("git 命令不可用") from exc
        except subprocess.CalledProcessError as exc:
            raise SkillImportError(
                f"git clone 失败: {exc.stderr.decode(errors='replace')[:200]}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise SkillImportError("git clone 超时") from exc
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _validate_git_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in _ALLOWED_GIT_PROTOCOLS:
            raise SkillImportError(
                f"Git 协议不允许: {parsed.scheme}（仅允许 {sorted(_ALLOWED_GIT_PROTOCOLS)}）"
            )
        host = (parsed.hostname or "").lower()
        if not host:
            raise SkillImportError("Git 地址缺少主机名")
        if host in _BLOCKED_HOST_LITERALS:
            raise SkillImportError(f"Git 主机被禁止: {host}")
        if any(host.endswith(s) for s in _BLOCKED_HOST_SUFFIXES):
            raise SkillImportError(f"Git 内网/本机地址被禁止: {host}")
        if any(host.startswith(p) for p in _PRIVATE_IP_PREFIXES):
            raise SkillImportError(f"Git 私有 IP 地址被禁止: {host}")

    # ── 安全校验 ──────────────────────────────────────────────────

    def _validate_extension_whitelist(self, files: dict[str, str]) -> None:
        for path in files:
            ext = Path(path).suffix.lower()
            if ext and ext not in ALLOWED_EXTENSIONS:
                raise SkillImportError(
                    f"文件扩展名不在白名单: {path}（{ext}）"
                )

    def _validate_content_safety(self, files: dict[str, str]) -> None:
        # 复用 P2 校验器对原始文件做敏感内容/脚本安全检测（仅文件安全，不含结构校验）
        report = self._validator.validate_files(files)
        blocking = [i for i in report.issues if i.severity.value == "blocking"]
        if blocking:
            raise SkillImportError(
                f"导入内容未通过安全校验: {blocking[0].code} — {blocking[0].message}"
            )

    # ── 草稿创建 ──────────────────────────────────────────────────

    def _create_import_draft(
        self,
        *,
        files: dict[str, str],
        source_label: str,
        created_by: str,
    ) -> SkillDraft:
        structured_config = self._infer_config_from_files(files)
        skill_id = str(structured_config["basic"]["skill_id"] or "imported_skill")
        skill_name = str(structured_config["basic"]["skill_name"] or skill_id)
        # 直接通过存储层创建，绕过 draft_service 的模板构造
        import uuid
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        draft = SkillDraft(
            draft_id=f"draft-{uuid.uuid4().hex[:12]}",
            skill_id=skill_id,
            skill_name=skill_name,
            source_type=SkillDraftSourceType.IMPORT,
            structured_config=structured_config,
            raw_files=files,
            status="editing",
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        storage = self._draft_service._storage  # noqa: SLF001
        return storage.save_draft(draft)

    @staticmethod
    def _infer_config_from_files(files: dict[str, str]) -> dict[str, Any]:
        """从导入文件的 skill_manifest.yaml 推断 structured_config。"""
        config: dict[str, Any] = {
            "basic": {"skill_id": "", "skill_name": "", "description": "", "owner": ""},
            "business_mounting": {
                "business_action": "",
                "business_object": "",
                "include_keywords": [],
                "excluded_intents": [],
            },
            "inputs": [],
            "schemas": {},
        }
        manifest_content = files.get("skill_manifest.yaml")
        if manifest_content:
            import yaml

            try:
                manifest = yaml.safe_load(manifest_content) or {}
                config["basic"]["skill_id"] = manifest.get("skill_id", "")
                config["basic"]["skill_name"] = manifest.get("skill_name", "")
                config["business_mounting"]["business_action"] = manifest.get(
                    "business_action", ""
                )
                config["business_mounting"]["business_object"] = manifest.get(
                    "business_object", ""
                )
                config["business_mounting"]["include_keywords"] = list(
                    manifest.get("supported_intents", []) or []
                )
                config["business_mounting"]["excluded_intents"] = list(
                    manifest.get("excluded_intents", []) or []
                )
            except yaml.YAMLError:
                pass
        if not config["basic"]["skill_id"]:
            config["basic"]["skill_id"] = "imported_skill"
        return config


def _strip_top_level_dir(name: str) -> str:
    """ZIP 成员去掉顶层目录前缀（如 settlement_explain_skill/SKILL.md → SKILL.md）。"""
    parts = Path(name).parts
    if len(parts) > 1:
        return "/".join(parts[1:])
    return name


def _is_symlink_attr(external_attr: int) -> bool:
    """检测 ZIP 条目的 Unix 符号链接位（0xA000）。"""
    return (external_attr >> 16 & 0o170000) == 0o120000
