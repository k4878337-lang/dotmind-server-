import asyncio
import re
from typing import AsyncGenerator, List, Dict, Optional
from app.services.llm.base import BaseLLMProvider

class MockAgentProvider(BaseLLMProvider):
    """
    Intelligent Context-Aware Simulated Agent Provider.
    Used when running offline or without an active external API key.
    Provides direct, natural answers for greetings/identity, truthful capability descriptions,
    and helpful technical explanations for coding, Python errors, SEO, and research without fabricating tool actions.
    """

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        system_instruction: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        last_message = messages[-1]["content"] if messages else "Hello"
        lower_prompt = last_message.lower().strip()

        # 0. Connection Test Hooks
        if "gemini_connection_test_731" in lower_prompt:
            body_text = "[Offline Simulator] Live Gemini test requires an active Gemini API key. Provider: offline_simulator"
        elif "dotmind_connection_test_731" in lower_prompt:
            body_text = "DOTMIND_CONNECTION_TEST_731"
        elif any(p in lower_prompt for p in ["test my currently selected model connection", "test model connection", "test connection"]):
            body_text = (
                "**Model Connection Status: Offline Mode**\n\n"
                "• **Provider:** `offline_simulator`\n"
                "• **Model:** `local-simulator`\n"
                "• **Result:** No external Gemini API key is configured for this session. "
                "To make a live API request and verify connection to Google Gemini, "
                "please enter your personal Gemini API key in the **AI Provider Gateway**."
            )
        elif any(p in lower_prompt for p in ["list the models actually available", "list available models", "discover models"]):
            body_text = (
                "**Configured Provider:** `offline_simulator`\n\n"
                "In offline simulation mode, no external models are reachable. "
                "When your Gemini API key is configured, live discovery queries the Google Generative Language API (`v1beta/models`) "
                "and retrieves verified models such as `gemini-2.5-flash`, `gemini-2.0-flash`, and `gemini-1.5-pro`."
            )
        elif any(p in lower_prompt for p in ["tell me the verified provider and model", "verified provider and model"]):
            body_text = (
                "**Verified Request Diagnostics:**\n\n"
                "• **Provider:** `offline_simulator`\n"
                "• **Model:** `local-simulator`\n"
                "• **Active Route:** Local offline simulation engine\n"
                "• **Note:** To route requests to Google Gemini, provide your API key in AI Provider Gateway."
            )
        elif any(p in lower_prompt for p in ["diagnose a model connection timeout", "connection timeout"]):
            body_text = (
                "### Diagnostic Methodology: Model Connection Timeout\n\n"
                "*(Note: Describing diagnostic steps only. No live network probes have been executed for this inquiry.)*\n\n"
                "1. **DNS Resolution:** Verify if `generativelanguage.googleapis.com` resolves successfully to Google IP addresses.\n"
                "2. **Network Route & Firewall:** Check whether outbound port 443 (HTTPS) is accessible without proxy interference.\n"
                "3. **Client-Side Timeout Configuration:** Ensure client timeout in `ApiClient.kt` (30s) and `GeminiProvider` (60s) is sufficient for complex reasoning queries.\n"
                "4. **Upstream Server Health:** Inspect HTTP response status codes (e.g. 504 Gateway Timeout or 429 Rate Limit).\n"
                "5. **Local Microservice Status:** If routing via `@google/genai` Node service, confirm `http://127.0.0.1:8001/health` is responsive."
            )
        elif system_instruction and "--- TOOL EXECUTION RESULTS (ACTUAL DATA) ---" in system_instruction:
            tool_data_section = system_instruction.split("--- TOOL EXECUTION RESULTS (ACTUAL DATA) ---")[-1].strip()
            body_text = f"### Verified Tool Execution Results\n\n{tool_data_section}\n\n*(Execution performed locally on verified workspace tools.)*"
        # 1. Simple Greetings
        elif lower_prompt in ["hi", "hi!", "hi.", "hi dotmind"]:
            body_text = "Hi! I'm DotMind. How can I help you today?"

        elif lower_prompt in ["hello", "hello!", "hello.", "hello dotmind", "hey", "hey dotmind", "helo", "namaste", "salam"]:
            body_text = "Hello! I'm DotMind, your personal AI agent. What would you like to work on today?"

        # 2. Name / Identity Inquiries
        elif any(phrase in lower_prompt for phrase in ["what is your name", "what's your name", "who are you", "your name"]):
            body_text = "I'm DotMind, your AI assistant."

        # 3. Truthful Capabilities Inquiry
        elif any(phrase in lower_prompt for phrase in ["what can you do", "what are your capabilities", "what do you do", "help me with"]):
            body_text = (
                "I am DotMind, your personal mobile AI agent. Here is what I can do:\n\n"
                "• **AI Conversations & Reasoning:** Answering questions, explaining concepts, and problem-solving.\n"
                "• **Android & Jetpack Compose:** Mobile architecture, UI design, edge-to-edge window insets, and Gradle builds.\n"
                "• **Technical SEO Auditing:** Analyzing websites, meta tags, Schema markup, and Core Web Vitals.\n"
                "• **GitHub Research:** Discovering open-source repositories and inspecting architectural samples.\n"
                "• **Code Inspection & Debugging:** Examining project files, Python errors, and codebase structure.\n"
                "• **Persistent Memory:** Retaining user preferences, projects, and personal instructions.\n"
                "• **Autonomous Task Engine:** Planning and tracking multi-step objectives with transparent execution logs.\n\n"
                "*(Currently operating in Offline Mode. Enter your Gemini API key in the AI Provider Gateway to activate live multimodal web research and real-time reasoning.)*"
            )

        # 4. Python Error Explanation & Debugging
        elif any(term in lower_prompt for term in ["explain this python error", "python error", "traceback", "indexerror", "keyerror", "attributeerror", "typeerror", "valueerror", "syntaxerror", "nameerror", "zerodivisionerror", "importerror"]):
            error_type = "Python Error"
            explanation = "This error occurs when an operation is executed on an unexpected data type or invalid index."
            solution = "Check the variable type and verify bounds before accessing elements."

            if "indexerror" in lower_prompt:
                error_type = "IndexError"
                explanation = "An `IndexError: list index out of range` occurs when trying to access a sequence item with an index that is outside the range of valid indices (0 to len - 1)."
                solution = "Verify the list is not empty with `if my_list:` or `if 0 <= index < len(my_list):` before accessing `my_list[index]`."
            elif "keyerror" in lower_prompt:
                error_type = "KeyError"
                explanation = "A `KeyError` occurs when attempting to access a dictionary key that does not exist."
                solution = "Use `dict.get(key, default)` or check existence with `if key in my_dict:` before indexing."
            elif "attributeerror" in lower_prompt:
                error_type = "AttributeError"
                explanation = "An `AttributeError` (e.g. `'NoneType' object has no attribute '...'`) occurs when referencing an attribute or method on an object that evaluates to `None` or an incompatible type."
                solution = "Add a guard check `if obj is not None:` or inspect the return value of previous function calls."
            elif "typeerror" in lower_prompt:
                error_type = "TypeError"
                explanation = "A `TypeError` occurs when an operation or function is applied to an object of inappropriate type (e.g. adding string and integer)."
                solution = "Ensure operands match expected types or explicitly convert with `str()`, `int()`, or `float()`."
            elif "syntaxerror" in lower_prompt:
                error_type = "SyntaxError"
                explanation = "A `SyntaxError` indicates Python encountered invalid grammar, such as missing colons `:`, unmatched parentheses `()`, or improper indentation."
                solution = "Review the line indicated in the traceback for missing colons, unbalanced brackets, or mixed tabs and spaces."

            body_text = (
                f"### Explanation of {error_type}\n\n"
                f"{explanation}\n\n"
                "**How to Fix:**\n"
                f"- {solution}\n\n"
                "```python\n"
                "# Example Safe Pattern\n"
                "try:\n"
                "    # Your operation here\n"
                "    pass\n"
                "except Exception as e:\n"
                "    print(f'Handled cleanly: {e}')\n"
                "```"
            )

        # 5. Project Fix / Workspace Maintenance
        elif any(phrase in lower_prompt for phrase in ["fix this project", "fix project", "inspect project"]):
            body_text = (
                "**Project Inspection & Diagnostic Plan:**\n\n"
                "1. **Inspect Workspace:** Check project files, directory structure, and configuration.\n"
                "2. **Identify Root Causes:** Review backend and Android build outputs for syntax, dependency, or layout errors.\n"
                "3. **Apply Targeted Fixes:** Update code while preserving existing features and comments.\n"
                "4. **Verify with Tests:** Execute test suites to confirm fixes.\n\n"
                "*(Connect your Gemini API key in AI Gateway for live autonomous code modifications and testing.)*"
            )

        # 6. Android / Jetpack Compose Guidance
        elif any(w in lower_prompt for w in ["android", "compose", "apk", "mobile app"]):
            body_text = (
                "### Android & Jetpack Compose Architecture\n\n"
                "Key practices for modern Android applications:\n\n"
                "• **Window Insets:** Use `.navigationBarsPadding()` and `.imePadding()` on bottom input bars to avoid keyboard and navigation bar overlap.\n"
                "• **State Hoisting:** Keep composables stateless; pass UI state down and emit event callbacks up.\n"
                "• **Smart Auto-Scroll:** Scroll to newest messages while preserving user freedom to inspect history.\n"
                "• **Key Management:** Encrypt sensitive tokens using Android Keystore AES-256-GCM with persistent fallback storage."
            )

        # 7. SEO & Web Guidance
        elif any(w in lower_prompt for w in ["seo", "meta tag", "sitemap", "website", "crawl"]):
            body_text = (
                "### Technical SEO & Web Performance\n\n"
                "Key technical SEO standards:\n\n"
                "• **Metadata:** Descriptive `<title>` (30-65 chars) and meta `<description>` (70-160 chars) on every canonical page.\n"
                "• **Canonical Links:** `<link rel=\"canonical\" href=\"...\">` to eliminate duplicate content penalties.\n"
                "• **Structured Data:** Schema.org JSON-LD for rich search results and AI search engine visibility (GEO).\n"
                "• **Core Web Vitals:** Responsive mobile viewports, image dimensions to prevent CLS, and fast LCP."
            )

        # 8. GitHub Research
        elif any(w in lower_prompt for w in ["github", "repository", "repo", "readme"]):
            body_text = (
                "### GitHub Research & Reference Architecture\n\n"
                "Curated architectural references available in `resources/github/`:\n\n"
                "• **compose-samples:** Official Jetpack Compose patterns (Jetcaster, Jetsnack, Crane, Reply).\n"
                "• **nowinandroid:** Production-grade modern Android architecture showcase.\n\n"
                "*(Enter your Gemini API key in AI Gateway for live multimodal GitHub search and README inspection.)*"
            )

        # 9. Coding & Debugging
        elif any(w in lower_prompt for w in ["code", "function", "class", "debug", "error", "exception"]):
            body_text = (
                "### Code Inspection & Debugging\n\n"
                "To diagnose your issue, provide the code snippet and error traceback. "
                "I will analyze the call stack, identify root causes, and provide an exact code fix."
            )

        # 10. Default General Response
        else:
            body_text = (
                "I am DotMind, your personal AI assistant. "
                "How can I help you with your coding, Android development, SEO, or task planning today?\n\n"
                "*(Tip: Enter your Gemini API key in the AI Provider Gateway to activate real-time web research, code execution, and live AI intelligence.)*"
            )

        # Stream response asynchronously
        words = body_text.split(" ")
        for i, word in enumerate(words):
            chunk = word + (" " if i < len(words) - 1 else "")
            yield chunk
            await asyncio.sleep(0.015)
