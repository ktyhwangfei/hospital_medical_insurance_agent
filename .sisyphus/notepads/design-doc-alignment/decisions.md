# Design-Doc Alignment Plan - Decisions

## Architecture Decisions

1. **Backend Route Organization**: Follow existing pattern (routes.py, skill_routes.py, mcp_routes.py)
   - Knowledge: `src/runtime/api/knowledge_routes.py`
   - Model: `src/runtime/api/model_routes.py`

2. **Admin Frontend**: Replace `knowledge-explorer.tsx` with new `knowledge-management.tsx`
   - Keep existing KnowledgeExplorer for reference during transition
   - New component uses proper API calls, no mock data

3. **Portal Frontend**: Keep separate routing (not SPA tabs)
   - Current Next.js page-based routing is adequate
   - Extract SettlementExceptionList from page.tsx

4. **Mock Data Strategy**: Backend routes first, then frontend
   - Frontend components can use real API calls after backend routes are created
   - No mock fallback in production code per prototype v2.0
