"""SkillImportService 单元测试（P3）。

覆盖 ZIP 安全校验（路径穿越/符号链接/大小/扩展名）、受控目录越界、
Git 地址校验、敏感内容拦截、正常导入生成草稿。
"""

from __future__ import annotations

import io
import struct
import zipfile

import pytest

from src.data_platform.storage.skill.draft_in_memory import (
    InMemorySkillDraftStorage,
)
from src.runtime.skill_management.draft_service import SkillDraftService
from src.runtime.skill_management.import_service import (
    SkillImportError,
    SkillImportService,
)


def _service(*, import_root=None) -> tuple[SkillImportService, SkillDraftService]:
    draft_service = SkillDraftService(storage=InMemorySkillDraftStorage())
    return (
        SkillImportService(draft_service, import_root=import_root),
        draft_service,
    )


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _zip_with_symlink() -> bytes:
    """构造一个含符号链接条目的 ZIP。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("link.txt")
        # Unix symlink mode: 0o120000
        info.external_attr = (0o120000 << 16) | 0o777
        zf.writestr(info, "target.txt")
    return buf.getvalue()


# ── ZIP 导入 ──────────────────────────────────────────────────────


def test_import_zip_creates_draft():
    svc, draft_service = _service()
    zbytes = _make_zip(
        {
            "pkg/skill_manifest.yaml": (
                "skill_id: imported\nskill_name: Imported\n"
                "business_action: explain\nbusiness_object: settlement\n"
            ),
            "pkg/SKILL.md": "# Imported",
        }
    )
    draft = svc.import_from_zip(
        upload_bytes=zbytes, filename="pkg.zip", created_by="u"
    )
    assert draft.source_type.value == "import"
    assert draft.skill_id == "imported"
    assert draft.skill_name == "Imported"
    assert "SKILL.md" in draft.raw_files
    assert draft.structured_config["business_mounting"]["business_action"] == "explain"


def test_import_zip_path_traversal_rejected():
    svc, _ = _service()
    zbytes = _make_zip({"../escape.txt": "evil"})
    with pytest.raises(SkillImportError, match="非法路径"):
        svc.import_from_zip(upload_bytes=zbytes, filename="x.zip", created_by="u")


def test_import_zip_absolute_path_rejected():
    svc, _ = _service()
    zbytes = _make_zip({"/etc/passwd": "x"})
    with pytest.raises(SkillImportError, match="非法路径"):
        svc.import_from_zip(upload_bytes=zbytes, filename="x.zip", created_by="u")


def test_import_zip_symlink_rejected():
    svc, _ = _service()
    zbytes = _zip_with_symlink()
    with pytest.raises(SkillImportError, match="符号链接"):
        svc.import_from_zip(upload_bytes=zbytes, filename="x.zip", created_by="u")


def test_import_zip_bad_zip_rejected():
    svc, _ = _service()
    with pytest.raises(SkillImportError, match="不是合法的 ZIP"):
        svc.import_from_zip(upload_bytes=b"not a zip", filename="x.zip", created_by="u")


def test_import_zip_empty_rejected():
    svc, _ = _service()
    zbytes = _make_zip({})
    with pytest.raises(SkillImportError, match="不包含任何文件"):
        svc.import_from_zip(upload_bytes=zbytes, filename="x.zip", created_by="u")


def test_import_zip_extension_whitelist():
    svc, _ = _service()
    zbytes = _make_zip({"pkg/evil.exe": "binary"})
    with pytest.raises(SkillImportError, match="扩展名不在白名单"):
        svc.import_from_zip(upload_bytes=zbytes, filename="x.zip", created_by="u")


def test_import_zip_sensitive_content_rejected():
    svc, _ = _service()
    zbytes = _make_zip({"pkg/config.yaml": "key: AKIAIOSFODNN7EXAMPLE"})
    with pytest.raises(SkillImportError, match="安全校验"):
        svc.import_from_zip(upload_bytes=zbytes, filename="x.zip", created_by="u")


def test_import_zip_strips_top_level_dir():
    svc, _ = _service()
    zbytes = _make_zip({"my_skill/SKILL.md": "# Hi", "my_skill/skills.txt": "x"})
    # .txt 在白名单
    draft = svc.import_from_zip(
        upload_bytes=zbytes, filename="x.zip", created_by="u"
    )
    assert "SKILL.md" in draft.raw_files
    assert "skills.txt" in draft.raw_files


# ── 受控目录导入 ──────────────────────────────────────────────────


def test_import_dir_creates_draft(tmp_path):
    root = tmp_path / "imports"
    pkg = root / "my_skill"
    pkg.mkdir(parents=True)
    (pkg / "SKILL.md").write_text("# Hi", encoding="utf-8")
    (pkg / "skill_manifest.yaml").write_text(
        "skill_id: my_skill\nskill_name: My\nbusiness_action: explain\nbusiness_object: settlement\n",
        encoding="utf-8",
    )
    svc, _ = _service(import_root=root)
    draft = svc.import_from_controlled_dir(
        relative_path="my_skill", created_by="u"
    )
    assert draft.skill_id == "my_skill"
    assert "SKILL.md" in draft.raw_files


def test_import_dir_path_escape_rejected(tmp_path):
    root = tmp_path / "imports"
    root.mkdir()
    svc, _ = _service(import_root=root)
    with pytest.raises(SkillImportError, match="路径越界"):
        svc.import_from_controlled_dir(
            relative_path="../escape", created_by="u"
        )


def test_import_dir_disabled_without_root():
    svc, _ = _service(import_root=None)
    with pytest.raises(SkillImportError, match="未配置"):
        svc.import_from_controlled_dir(relative_path="x", created_by="u")


def test_import_dir_missing_rejected(tmp_path):
    root = tmp_path / "imports"
    root.mkdir()
    svc, _ = _service(import_root=root)
    with pytest.raises(SkillImportError, match="不存在"):
        svc.import_from_controlled_dir(relative_path="missing", created_by="u")


# ── Git 地址校验 ──────────────────────────────────────────────────


def test_git_url_rejects_invalid_protocol():
    svc, _ = _service()
    with pytest.raises(SkillImportError, match="协议不允许"):
        svc._validate_git_url("ftp://example.com/repo.git")  # noqa: SLF001


def test_git_url_rejects_localhost():
    svc, _ = _service()
    with pytest.raises(SkillImportError, match="主机被禁止"):
        svc._validate_git_url("https://localhost/repo.git")  # noqa: SLF001


def test_git_url_rejects_private_ip():
    svc, _ = _service()
    with pytest.raises(SkillImportError, match="私有 IP"):
        svc._validate_git_url("https://192.168.1.1/repo.git")  # noqa: SLF001


def test_git_url_accepts_public_https():
    svc, _ = _service()
    svc._validate_git_url("https://github.com/org/repo.git")  # noqa: SLF001
