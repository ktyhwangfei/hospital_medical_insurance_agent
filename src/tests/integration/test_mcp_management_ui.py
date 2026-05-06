from pathlib import Path


def test_mcp_admin_static_page_contains_required_sections():
    html = Path("src/static/mcp-admin.html").read_text(encoding="utf-8")
    assert "MCP 服务管理" in html
    assert "连接测试" in html
    assert "能力浏览" in html
    assert "策略配置" in html
    assert "审计查看" in html
    assert "Authorization" not in html
