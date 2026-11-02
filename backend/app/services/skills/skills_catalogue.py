from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class SkillInfo(BaseModel):
    name: str
    category: str
    description: str
    official_sources: List[str] = Field(default_factory=list)
    key_principles: List[str] = Field(default_factory=list)
    recommended_tools: List[str] = Field(default_factory=list)
    reference_snippet: str = ""

class SkillsCatalogue:
    def __init__(self):
        self._skills: Dict[str, SkillInfo] = {}
        self._load_catalogue()

    def get(self, name: str) -> Optional[SkillInfo]:
        return self._skills.get(name)

    def search(self, query: str, category: Optional[str] = None) -> List[SkillInfo]:
        results = []
        q_lower = query.lower()
        for skill in self._skills.values():
            if category and skill.category.lower() != category.lower():
                continue
            if (
                q_lower in skill.name.lower() or
                q_lower in skill.description.lower() or
                any(q_lower in p.lower() for p in skill.key_principles)
            ):
                results.append(skill)
        return results

    def list_all(self) -> List[SkillInfo]:
        return list(self._skills.values())

    def _load_catalogue(self):
        # 1. Android Jetpack Compose Development
        self._skills["android-development"] = SkillInfo(
            name="android-development",
            category="mobile",
            description="Modern Android architecture using Jetpack Compose, ViewModels, Kotlin Coroutines, and Gradle.",
            official_sources=[
                "https://github.com/android/compose-samples",
                "https://github.com/android/nowinandroid"
            ],
            key_principles=[
                "State Hoisting: Keep composables stateless by passing state down and events up.",
                "Single Activity Architecture with Jetpack Navigation Compose.",
                "Android Keystore-backed AES-256-GCM encryption for personal tokens.",
                "Use MaterialTheme color tokens for dynamic obsidian/dark mode support."
            ],
            recommended_tools=["project_inspector", "file_reader"],
            reference_snippet="""// State Hoisting Pattern in Compose:
@Composable
fun MessageInput(text: String, onTextChange: (String) -> Unit, onSend: () -> Unit) {
    Row {
        TextField(value = text, onValueChange = onTextChange)
        IconButton(onClick = onSend) { Icon(Icons.Default.Send, contentDescription = "Send") }
    }
}"""
        )

        # 2. Website SEO & Technical Audit
        self._skills["website-seo"] = SkillInfo(
            name="website-seo",
            category="seo",
            description="Google Search Central technical guidelines: metadata, crawlability, indexing, and OpenGraph.",
            official_sources=[
                "https://developers.google.com/search/docs"
            ],
            key_principles=[
                "Single distinct <h1> tag per page matching title intent.",
                "Meta description between 70 and 160 characters with clear call to action.",
                "Canonical tag <link rel='canonical'> to avoid duplicate content penalties.",
                "Image alt attributes with descriptive semantic context."
            ],
            recommended_tools=["seo_analyzer", "http_tester"],
            reference_snippet="""<!-- SEO Meta Essentials: -->
<title>Product Name — Feature Overview | Brand</title>
<meta name="description" content="Concise summary between 70 and 160 characters.">
<link rel="canonical" href="https://example.com/canonical-page" />
<meta property="og:title" content="Product Name" />
<meta property="og:image" content="https://example.com/og-image.jpg" />"""
        )

        # 3. Web & Mobile Animations
        self._skills["animation-design"] = SkillInfo(
            name="animation-design",
            category="animation",
            description="Motion design, transitions, and gesture animations using Compose and React Motion.",
            official_sources=[
                "https://motion.dev/docs/react"
            ],
            key_principles=[
                "Respect reduced-motion accessibility preferences.",
                "Use spring-based physics over linear easing for natural feel.",
                "Prefer GPU-accelerated transforms (scale, alpha, translation) to prevent recomposition jank."
            ],
            recommended_tools=["file_reader"],
            reference_snippet="""// Jetpack Compose Animated Visibility:
AnimatedVisibility(
    visible = isVisible,
    enter = fadeIn(animationSpec = tween(300)) + slideInVertically(),
    exit = fadeOut(animationSpec = tween(200))
) {
    ContentCard()
}"""
        )

        # 4. GitHub REST Research
        self._skills["github-research"] = SkillInfo(
            name="github-research",
            category="research",
            description="Programmatic GitHub exploration: repository search, README extraction, license inspection.",
            official_sources=[
                "https://docs.github.com/en/rest"
            ],
            key_principles=[
                "Inspect repository license (MIT/Apache vs GPL/Proprietary) before importing dependencies.",
                "Check stars, forks, and last commit recency to avoid abandoned packages.",
                "Handle GitHub rate limits gracefully (60 req/hr unauthenticated)."
            ],
            recommended_tools=["github_researcher"],
            reference_snippet="""// GitHub REST API:
GET https://api.github.com/search/repositories?q={query}&per_page=5
Headers: Accept: application/vnd.github.v3+json"""
        )

        # 5. FastAPI Backend Architecture
        self._skills["fastapi-backend"] = SkillInfo(
            name="fastapi-backend",
            category="backend",
            description="High-performance asynchronous Python backend with SQLAlchemy async and SSE streaming.",
            official_sources=[
                "https://fastapi.tiangolo.com/"
            ],
            key_principles=[
                "Use async sessions with aiosqlite or asyncpg for zero-blocking I/O.",
                "Validate incoming DTOs strictly with Pydantic BaseModel.",
                "Stream AI responses using Server-Sent Events (SSE) with SSE-Starlette."
            ],
            recommended_tools=["http_tester", "test_runner"],
            reference_snippet="""@router.get('/health')
async def health():
    return {'status': 'healthy', 'service': 'DOTMIND'}"""
        )

skills_catalogue = SkillsCatalogue()
