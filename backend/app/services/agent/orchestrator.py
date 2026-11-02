import re
import json
import base64
from typing import AsyncGenerator, Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent.context_engine import context_engine
from app.services.agent.intent_router import intent_router, IntentClassification
from app.services.tools.tool_registry import tool_registry, ToolResult
from app.services.tools.document_parser import extract_document_text
from app.services.agent.subagents import multi_agent_coordinator
from app.services.agent.react_engine import react_engine, ReActResult
from app.services.skills.skills_catalogue import skills_catalogue
from app.services.llm.base import BaseLLMProvider
from app.services.llm.gemini import GeminiProvider, GeminiAPIException
from app.services.llm.mock import MockAgentProvider
from app.services.llm.router import llm_router
from app.config import settings

class AgentOrchestrator:
    """Coordinates intent classification, tool invocation, context synthesis, and streaming."""

    async def run_agent_loop(
        self,
        db: AsyncSession,
        user_id: str,
        conversation_id: str,
        user_message: str,
        base_instructions: str,
        personal_api_key: Optional[str] = None,
        selected_model: Optional[str] = None,
        attachments: Optional[List[Any]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        # Step 1: Intent Classification
        intent = intent_router.classify(user_message)

        # Emit status event
        status_text = "Thinking…" if intent.category == "GENERAL_CHAT" else f"Understanding your request ({intent.category})"
        yield {
            "event": "status",
            "data": json.dumps({
                "status": status_text,
                "goal": intent.explanation
            })
        }

        # Emit thought event (backward compatible)
        yield {
            "event": "thought",
            "data": json.dumps({
                "intent": intent.category,
                "confidence": intent.confidence,
                "workflow": intent.explanation,
                "tools": intent.suggested_tools
            })
        }

        # Step 2: Multi-step Plan generation via PlannerAgent
        plan_steps: List[str] = []
        agent_plan = await multi_agent_coordinator.plan_goal(user_message, intent.category)
        if intent.category != "GENERAL_CHAT" and agent_plan.get("steps"):
            plan_steps = [f"[{s['agent']}] {s['action']}" for s in agent_plan["steps"]]
            yield {
                "event": "plan",
                "data": json.dumps({
                    "goal": intent.explanation,
                    "steps": plan_steps,
                    "subagents": [s["agent"] for s in agent_plan["steps"]]
                })
            }

        # Step 3: Autonomous Tool Invocation based on Intent
        tool_results: List[ToolResult] = []

        if intent.category == "GITHUB_RESEARCH":
            query = user_message
            for noise in ["search", "find", "github", "repo", "repositories", "for", "look up", "me"]:
                query = re.sub(rf"\b{noise}\b", "", query, flags=re.IGNORECASE)
            query = query.strip() or "android compose"

            yield {
                "event": "tool_start",
                "data": json.dumps({"tool": "github_researcher", "action": f"Searching GitHub for '{query}'"})
            }
            yield {
                "event": "tool_call",
                "data": json.dumps({"tool": "github_researcher", "arguments": {"query": query}})
            }
            res = await tool_registry.execute("github_researcher", {"query": query})
            tool_results.append(res)
            yield {
                "event": "tool_result",
                "data": json.dumps({
                    "tool": "github_researcher",
                    "status": res.status,
                    "latency_ms": res.latency_ms,
                    "summary": f"GitHub search {res.status} ({res.latency_ms}ms)"
                })
            }

        elif intent.category == "SEO_AUDIT":
            url_match = re.search(r"https?://[^\s]+", user_message)
            target_url = url_match.group(0) if url_match else "http://localhost:8000"

            yield {
                "event": "tool_start",
                "data": json.dumps({"tool": "seo_analyzer", "action": f"Auditing SEO for {target_url}"})
            }
            yield {
                "event": "tool_call",
                "data": json.dumps({"tool": "seo_analyzer", "arguments": {"url": target_url}})
            }
            res = await tool_registry.execute("seo_analyzer", {"url": target_url})
            tool_results.append(res)
            yield {
                "event": "tool_result",
                "data": json.dumps({
                    "tool": "seo_analyzer",
                    "status": res.status,
                    "latency_ms": res.latency_ms,
                    "summary": f"SEO analysis {res.status} ({res.latency_ms}ms)"
                })
            }

        elif intent.category == "TESTING_QA":
            target = "tests/test_phase2_security_and_tools.py"
            lower_msg = user_message.lower()
            if "health" in lower_msg:
                target = "tests/test_health.py"
            elif "all" in lower_msg or "full" in lower_msg:
                target = "tests/"
            elif "gateway" in lower_msg:
                target = "tests/test_gateway.py"
            elif "agent" in lower_msg:
                target = "tests/test_agent_system.py"

            yield {
                "event": "tool_start",
                "data": json.dumps({"tool": "test_runner", "action": f"Executing real pytest test suite ({target})"})
            }
            yield {
                "event": "tool_call",
                "data": json.dumps({"tool": "test_runner", "arguments": {"test_target": target}})
            }
            res = await tool_registry.execute("test_runner", {"test_target": target})
            tool_results.append(res)
            summary_txt = res.output.get("summary", "") if res.output else (res.error or "Test execution failed")
            yield {
                "event": "tool_result",
                "data": json.dumps({
                    "tool": "test_runner",
                    "status": res.status,
                    "latency_ms": res.latency_ms,
                    "summary": f"Pytest {res.status}: {summary_txt}"
                })
            }

        elif intent.category == "LOG_INSPECTION":
            yield {
                "event": "tool_start",
                "data": json.dumps({"tool": "log_inspector", "action": "Inspecting workspace server logs"})
            }
            yield {
                "event": "tool_call",
                "data": json.dumps({"tool": "log_inspector", "arguments": {"max_lines": 40}})
            }
            res = await tool_registry.execute("log_inspector", {"max_lines": 40})
            tool_results.append(res)
            yield {
                "event": "tool_result",
                "data": json.dumps({
                    "tool": "log_inspector",
                    "status": res.status,
                    "latency_ms": res.latency_ms,
                    "summary": f"Log inspection {res.status} ({res.output.get('lines_read', 0) if res.output else 0} lines)"
                })
            }

        elif intent.category in ["MOBILE_DEV", "CODING"]:
            file_match = re.search(r'\b([a-zA-Z0-9_\-/\\]+\.(?:py|kt|xml|json|gradle|kts|md|sh))\b', user_message)
            search_match = re.search(r'(?:find|search|where is|locate)\s+["\']?([^"\']+)["\']?', user_message, re.IGNORECASE)

            if file_match and any(w in user_message.lower() for w in ["read", "check", "inspect", "show", "open", "view"]):
                file_rel = file_match.group(1)
                yield {
                    "event": "tool_start",
                    "data": json.dumps({"tool": "file_reader", "action": f"Reading file {file_rel}"})
                }
                yield {
                    "event": "tool_call",
                    "data": json.dumps({"tool": "file_reader", "arguments": {"relative_path": file_rel}})
                }
                res = await tool_registry.execute("file_reader", {"relative_path": file_rel, "max_lines": 120})
                tool_results.append(res)
                yield {
                    "event": "tool_result",
                    "data": json.dumps({
                        "tool": "file_reader",
                        "status": res.status,
                        "latency_ms": res.latency_ms,
                        "summary": f"Read {file_rel} ({res.status}, {res.latency_ms}ms)"
                    })
                }
            elif search_match and any(w in user_message.lower() for w in ["search", "find", "locate"]):
                q = search_match.group(1).strip()
                yield {
                    "event": "tool_start",
                    "data": json.dumps({"tool": "file_searcher", "action": f"Searching workspace for '{q}'"})
                }
                yield {
                    "event": "tool_call",
                    "data": json.dumps({"tool": "file_searcher", "arguments": {"query": q}})
                }
                res = await tool_registry.execute("file_searcher", {"query": q})
                tool_results.append(res)
                cnt = res.output.get("matches_count", 0) if res.output else 0
                yield {
                    "event": "tool_result",
                    "data": json.dumps({
                        "tool": "file_searcher",
                        "status": res.status,
                        "latency_ms": res.latency_ms,
                        "summary": f"Workspace search '{q}' ({res.status}, {cnt} matches)"
                    })
                }
            else:
                yield {
                    "event": "tool_start",
                    "data": json.dumps({"tool": "project_inspector", "action": "Inspecting project workspace"})
                }
                yield {
                    "event": "tool_call",
                    "data": json.dumps({"tool": "project_inspector", "arguments": {}})
                }
                res = await tool_registry.execute("project_inspector", {})
                tool_results.append(res)
                yield {
                    "event": "tool_result",
                    "data": json.dumps({
                        "tool": "project_inspector",
                        "status": res.status,
                        "latency_ms": res.latency_ms,
                        "summary": f"Workspace inspect {res.status} ({res.latency_ms}ms)"
                    })
                }

        elif intent.category == "API_INTEGRATION":
            url_match = re.search(r"https?://[^\s]+", user_message)
            if url_match:
                target_url = url_match.group(0)
                yield {
                    "event": "tool_start",
                    "data": json.dumps({"tool": "http_tester", "action": f"Probing {target_url}"})
                }
                yield {
                    "event": "tool_call",
                    "data": json.dumps({"tool": "http_tester", "arguments": {"url": target_url}})
                }
                res = await tool_registry.execute("http_tester", {"url": target_url})
                tool_results.append(res)
                yield {
                    "event": "tool_result",
                    "data": json.dumps({
                        "tool": "http_tester",
                        "status": res.status,
                        "latency_ms": res.latency_ms,
                        "summary": f"HTTP test {res.status} ({res.latency_ms}ms)"
                    })
                }

        # Step 4: Match Relevant Skills
        skills_matched = []
        for skill_name in intent.required_skills:
            s = skills_catalogue.get(skill_name)
            if s:
                skills_matched.append(s)

        output_rules = (
            "CRITICAL RESPONSE DIRECTIVES:\n"
            "- You are DotMind, a proactive personal AI agent.\n"
            "- Never output internal meta-commentary, persona reflections, or scratchpad planning steps like 'The user said...', 'Plan: 1...', or 'My persona is...'.\n"
            "- Output ONLY the clean, final, user-facing response.\n"
            "- Base your response strictly on the REAL TOOL EXECUTION RESULTS provided below.\n"
            "- If tests were run, report the exact passed and failed counts from the tool output. Never claim tests passed if they failed or were not executed.\n"
            "- If a capability, tool, or external network is unavailable, state it honestly. Never fabricate mock data or write 'Simulated for this report'.\n"
            "- For greetings (e.g. 'hi', 'hello'), respond concisely in 1-2 friendly sentences.\n"
            "- For name inquiries (e.g. 'what is your name'), state directly: 'I am DotMind, your personal AI agent.'\n"
            "- For capability inquiries (e.g. 'what can you do'), concisely explain your real implemented capabilities: "
            "AI chat & problem solving, Android Jetpack Compose architecture, technical SEO auditing, GitHub repository research, workspace code search/reading/writing, real pytest test execution, log inspection, persistent user memory, and autonomous task management.\n"
            "- Do not fabricate tool actions or test results that did not occur."
        )
        # Step 5: Assemble Context with Tool Injections and Skills
        enriched_instructions = [output_rules, base_instructions]
        if intent.category != "GENERAL_CHAT":
            enriched_instructions.append(f"Detected User Goal: {intent.category} ({intent.explanation})")

        if skills_matched:
            skill_texts = ["--- RELEVANT SKILL GUIDANCE ---"]
            for s in skills_matched:
                skill_texts.append(f"Skill [{s.name}]: {s.description}")
                for p in s.key_principles[:3]:
                    skill_texts.append(f"  • {p}")
            enriched_instructions.append("\n".join(skill_texts))

        if tool_results:
            tool_texts = ["--- TOOL EXECUTION RESULTS (ACTUAL DATA) ---"]
            for tr in tool_results:
                tool_texts.append(f"Tool [{tr.tool_name}] status={tr.status} ({tr.latency_ms}ms):")
                tool_texts.append(json.dumps(tr.output, indent=2)[:1500])
            enriched_instructions.append("\n".join(tool_texts))

        compiled_context = await context_engine.build_context(
            db=db,
            user_id=user_id,
            conversation_id=conversation_id,
            current_message=user_message,
            base_system_prompt="\n\n".join(enriched_instructions),
            selected_model=selected_model or "gemini-2.0-flash",
            include_project=intent.category in ["MOBILE_DEV", "CODING"]
        )

        # Step 5b: Multimodal and attachment synthesis with document text extraction
        if attachments and compiled_context.get("messages"):
            user_parts: List[Dict[str, Any]] = [{"text": user_message}]
            for att in attachments:
                att_dict = att.dict() if hasattr(att, "dict") else dict(att)
                mime = att_dict.get("mime_type", "")
                b64 = att_dict.get("base64_data")
                fname = att_dict.get("filename", "file")

                # Extract text from documents and PDFs via pypdf / text parser
                doc_text = extract_document_text(fname, mime, b64) if b64 else None
                if doc_text:
                    user_parts.append({
                        "text": f"\n\n--- EXTRACTED DOCUMENT CONTENT ({fname}) ---\n{doc_text[:25000]}\n--- END DOCUMENT CONTENT ---"
                    })

                # Attach inlineData for images, PDFs (for visual charts/diagrams), and videos
                if b64 and (mime.startswith("image/") or mime == "application/pdf" or mime.startswith("video/")):
                    if len(b64) <= 12_000_000:
                        user_parts.append({
                            "inline_data": {
                                "mime_type": mime,
                                "data": b64
                            },
                            "inlineData": {
                                "mimeType": mime,
                                "data": b64
                            }
                        })
                    else:
                        user_parts.append({
                            "text": f"\n[Large Attachment: {fname} ({mime}) exceeding 10MB inline limit; analyzed via metadata and text stream.]"
                        })
                elif not doc_text:
                    user_parts.append({"text": f"\n\n[Attachment: {fname} ({mime})]"})

            for i in range(len(compiled_context["messages"]) - 1, -1, -1):
                if compiled_context["messages"][i].get("role") == "user":
                    compiled_context["messages"][i]["parts"] = user_parts
                    break

        # Step 6: Route to Provider (Personal Key > Server Key > Smart Mock Provider)
        has_personal_key = bool(personal_api_key and personal_api_key.strip())
        is_gemini_active = has_personal_key or bool(settings.GEMINI_API_KEY)

        if has_personal_key:
            provider = GeminiProvider(
                api_key=personal_api_key.strip(),
                model=selected_model
            )
            provider_type = "google_gemini"
            provider_model = selected_model or settings.GEMINI_MODEL
        elif settings.GEMINI_API_KEY:
            provider = GeminiProvider(
                api_key=settings.GEMINI_API_KEY.strip(),
                model=selected_model
            )
            provider_type = "google_gemini"
            provider_model = selected_model or settings.GEMINI_MODEL
        else:
            provider = MockAgentProvider()
            provider_type = "offline_simulator"
            provider_model = "local-simulator"

        # Step 7: Stream Answer Tokens with ReAct Multi-Turn Reasoning & Error Interception
        error_encountered = None
        react_holder = ReActResult()
        try:
            if is_gemini_active and intent.category != "GENERAL_CHAT":
                # Execute iterative Thought -> Action -> Observation ReAct Loop
                async for event_payload in react_engine.execute_react_loop(
                    provider=provider,
                    messages=compiled_context["messages"],
                    system_instruction=compiled_context["system_instruction"],
                    initial_tool_results=tool_results,
                    is_offline_simulator=False,
                    result_holder=react_holder
                ):
                    yield event_payload
                # Merge any subsequent dynamically executed tools into tool_results for work_log
                tool_results = react_holder.tool_results
            else:
                # Direct streaming for general conversation, greetings, and offline simulation mode
                async for token in provider.stream_chat(
                    messages=compiled_context["messages"],
                    system_instruction=compiled_context["system_instruction"]
                ):
                    yield {
                        "event": "answer_delta",
                        "data": json.dumps({"delta": token})
                    }
                    yield {
                        "event": "token",
                        "data": json.dumps({"token": token})
                    }
        except GeminiAPIException as e:
            error_encountered = e
            yield {
                "event": "error",
                "data": json.dumps({
                    "error": e.message,
                    "error_code": e.error_code,
                    "provider": provider_type
                })
            }
        except Exception as e:
            err_msg = str(e)
            if personal_api_key and personal_api_key in err_msg:
                err_msg = err_msg.replace(personal_api_key, "[REDACTED_API_KEY]")
            error_encountered = e
            yield {
                "event": "error",
                "data": json.dumps({
                    "error": f"Agent streaming error: {err_msg}",
                    "error_code": "STREAMING_ERROR",
                    "provider": provider_type
                })
            }

        # Step 8: Emit Complete Work Log
        overall_status = "failed" if error_encountered else ("completed" if is_gemini_active else "offline_simulated")
        err_list = [error_encountered.message if isinstance(error_encountered, GeminiAPIException) else str(error_encountered)] if error_encountered else []
        work_log = {
            "goal": intent.explanation if intent.category != "GENERAL_CHAT" else "Direct conversation",
            "intent": intent.category,
            "provider": provider_type,
            "model": provider_model,
            "status": overall_status,
            "plan": plan_steps,
            "tools": [
                {
                    "name": tr.tool_name,
                    "status": tr.status,
                    "latency_ms": tr.latency_ms,
                    "summary": f"{tr.tool_name} {tr.status}"
                }
                for tr in tool_results
            ],
            "completed_work": (
                f"Failed: {err_list[0]}"
                if error_encountered
                else (f"Executed {len(tool_results)} tool(s) successfully" if tool_results else "Direct answer generated")
            ),
            "incomplete": "None" if not error_encountered else "Stream terminated prematurely due to provider error",
            "errors": err_list
        }
        yield {
            "event": "complete",
            "data": json.dumps({"work_log": work_log})
        }

agent_orchestrator = AgentOrchestrator()
