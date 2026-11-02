import re
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.memory import Memory

class MemoryService:
    @staticmethod
    def _calculate_score(query_tokens: set, content: str, importance: int) -> float:
        content_lower = content.lower()
        score = 0.0

        for token in query_tokens:
            if token in content_lower:
                score += 2.0

        # Substring / phrase match
        query_str = " ".join(query_tokens)
        if query_str and query_str in content_lower:
            score += 5.0

        # Importance boost: 1.0x to 2.0x
        multiplier = 1.0 + (importance - 1) * 0.25
        return score * multiplier

    async def search_relevant_memories(
        self,
        db: AsyncSession,
        user_id: str,
        query: str,
        category: Optional[str] = None,
        limit: int = 5
    ) -> List[Memory]:
        """Performs relevance-scored hybrid retrieval across active user memories."""
        stmt = select(Memory).where(Memory.user_id == user_id, Memory.is_active == True)
        if category:
            stmt = stmt.where(Memory.category == category)

        result = await db.execute(stmt)
        all_memories = result.scalars().all()

        if not all_memories:
            return []

        # Tokenize query
        stop_words = {"a", "an", "the", "in", "on", "at", "for", "to", "is", "of", "and", "or"}
        tokens = set(re.findall(r"\w+", query.lower())) - stop_words

        scored_memories = []
        for mem in all_memories:
            score = self._calculate_score(tokens, mem.content, mem.importance)
            scored_memories.append((score, mem))

        # Sort by score descending, then by updated_at
        scored_memories.sort(key=lambda x: (x[0], x[1].updated_at), reverse=True)

        # Return top N that have non-zero relevance, or most important recent if query is generic
        results = [m for s, m in scored_memories if s > 0][:limit]
        if not results:
            # Fallback to highest importance active memories
            results = sorted(all_memories, key=lambda m: (m.importance, m.updated_at), reverse=True)[:limit]

        return results

    async def format_memory_context(
        self,
        db: AsyncSession,
        user_id: str,
        query: str,
        limit: int = 4
    ) -> str:
        """Retrieves and formats user persistent memories into an agent context block."""
        memories = await self.search_relevant_memories(db, user_id, query, limit=limit)
        if not memories:
            return ""

        lines = [
            "--- USER PERSISTENT MEMORY CONTEXT ---",
            "Recalled preferences, project notes, and decisions from previous interactions:"
        ]
        for m in memories:
            lines.append(f"- [{m.category.upper()}] (importance: {m.importance}/5): {m.content}")
        lines.append("Honor these persisted user preferences and instructions throughout your response.\n")

        return "\n".join(lines)

memory_service = MemoryService()
