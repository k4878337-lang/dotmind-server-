import re
import json
import asyncio
from typing import AsyncGenerator, Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field

from app.services.tools.tool_registry import tool_registry, ToolResult
from app.services.llm.base import BaseLLMProvider

class ReActTurn(BaseModel):
    thought: Optional[str] = None
    action: Optional[str] = None
    action_input: Optional[Dict[str, Any]] = None
    final_answer: Optional[str] = None
    is_final: bool = False
    raw_text: str = ""

# Primary parameter fallbacks for tools when the model passes raw unquoted strings
TOOL_PRIMARY_PARAM = {
    "file_reader": "relative_path",
    "github_researcher": "query",
    "seo_analyzer": "url",
    "http_tester": "url",
    "file_searcher": "query",
    "test_runner": "test_target",
    "project_inspector": "subpath",
    "log_inspector": "log_file",
    "browser_navigator": "url",
}


def parse_react_turn(text: str) -> ReActTurn:
    """
    Parses a model response into structured Thought, Action, Action Input, or Final Answer.
    Handles loose JSON, markdown code fences, and unstructured single argument inputs.
    """
    raw = text.strip() if text else ""
    if not raw:
        return ReActTurn(is_final=True, final_answer="", raw_text="")

    # 1. Check for Final Answer:
    final_match = re.search(r"(?:Final\s*Answer\s*:|Answer\s*:)\s*(.*)", raw, re.DOTALL | re.IGNORECASE)
    
    # 2. Check for Action: and Action Input:
    action_match = re.search(r"Action\s*:\s*([a-zA-Z0-9_\-]+)", raw, re.IGNORECASE)
    input_match = re.search(r"Action\s*Input\s*:\s*(.+?)(?=(?:\n\s*Observation|\n\s*Thought|\n\s*Action|\n\s*Final\s*Answer|$))", raw, re.DOTALL | re.IGNORECASE)

    # 3. Extract Thought if present
    thought_match = re.search(r"Thought\s*:\s*(.+?)(?=(?:\n\s*Action|\n\s*Final\s*Answer|$))", raw, re.DOTALL | re.IGNORECASE)
    thought_text = thought_match.group(1).strip() if thought_match else None

    # If an Action is specified:
    if action_match:
        tool_name = action_match.group(1).strip()
        raw_input = input_match.group(1).strip() if input_match else "{}"

        # Clean markdown codeblocks
        if raw_input.startswith("```"):
            raw_input = re.sub(r"^```(?:json)?\s*", "", raw_input)
            raw_input = re.sub(r"\s*```$", "", raw_input).strip()

        parsed_input: Dict[str, Any] = {}
        try:
            val = json.loads(raw_input)
            if isinstance(val, dict):
                parsed_input = val
            else:
                # If parsed as primitive string/int
                primary = TOOL_PRIMARY_PARAM.get(tool_name, "query")
                parsed_input = {primary: str(val)}
        except Exception:
            # Fallback for plain unquoted string or key: value
            kv_match = re.match(r"^([a-zA-Z0-9_\-]+)\s*:\s*(.+)$", raw_input)
            if kv_match:
                k, v = kv_match.groups()
                parsed_input = {k.strip(): v.strip().strip("\"'")}
            else:
                primary = TOOL_PRIMARY_PARAM.get(tool_name, "query")
                parsed_input = {primary: raw_input.strip("\"'")}

        return ReActTurn(
            thought=thought_text,
            action=tool_name,
            action_input=parsed_input,
            is_final=False,
            raw_text=raw
        )

    # If no Action was found, treat as Final Answer
    final_text = final_match.group(1).strip() if final_match else raw
    return ReActTurn(
        thought=thought_text,
        final_answer=final_text,
        is_final=True,
        raw_text=raw
    )

def build_react_system_instruction(base_system_prompt: str) -> str:
    """Appends tool documentation and ReAct execution directives to system prompt."""
    tool_lines = ["--- AVAILABLE WORKSPACE TOOLS (REACT REASONING ENGINE) ---"]
    for name, defn in tool_registry._tools.items():
        params_summary = ", ".join(f"{k}: {v.get('type', 'any')}" for k, v in defn.parameters.get("properties", {}).items())
        tool_lines.append(f"• {name}({params_summary}): {defn.description}")

    react_rules = (
        "\n\n--- DYNAMIC REACT AGENT INSTRUCTIONS ---\n"
        "You are DotMind, an autonomous personal AI agent capable of iterative reasoning and acting (ReAct).\n"
        "When answering questions that require inspecting files, searching code, testing APIs, analyzing SEO, "
        "checking logs, or executing pytest suites, you MUST use the ReAct iterative format:\n\n"
        "Thought: <Your reasoning on what information is needed or what step to perform next>\n"
        "Action: <One of the registered tool names above>\n"
        "Action Input: <JSON object of parameters matching the tool's schema>\n\n"
        "After your action executes, you will receive an 'Observation: ...' with the real tool output.\n"
        "You can perform multiple turns of Thought -> Action -> Observation to thoroughly investigate.\n"
        "When you have collected all necessary evidence to solve the user's request, formulate your response as:\n\n"
        "Thought: <Final reasoning verifying that you have all facts from tool observations>\n"
        "Final Answer: <Your comprehensive, polite, clean answer. Do not include internal thoughts here>\n\n"
        "If NO tools are required (e.g. greetings, simple questions, or conceptual explanations), "
        "you may respond directly with:\n"
        "Final Answer: <Your response>"
    )

    return base_system_prompt + "\n\n" + "\n".join(tool_lines) + react_rules

class ReActResult:
    def __init__(self):
        self.tool_results: List[ToolResult] = []
        self.final_answer: str = ""

class ReActEngine:
    """
    Executes iterative multi-turn Thought -> Action -> Observation ReAct loop.
    Emits real-time SSE events for thoughts, tool calls, and final streaming tokens.
    """
    def __init__(self, max_turns: int = 4):
        self.max_turns = max_turns

    async def execute_react_loop(
        self,
        provider: BaseLLMProvider,
        messages: List[Dict[str, Any]],
        system_instruction: str,
        initial_tool_results: Optional[List[ToolResult]] = None,
        is_offline_simulator: bool = False,
        result_holder: Optional[ReActResult] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Runs the ReAct loop:
        1. Emits SSE status and tool events during turns.
        2. Streams final answer tokens directly to the client.
        3. Populates result_holder with accumulated tool_results and final answer text.
        """
        all_tool_results: List[ToolResult] = list(initial_tool_results or [])
        turn_messages = [dict(m) for m in messages]
        final_answer_accumulated: List[str] = []

        if result_holder is None:
            result_holder = ReActResult()

        # If running in offline simulator mode, bypass multi-turn LLM generation and stream directly
        if is_offline_simulator:
            async for token in provider.stream_chat(turn_messages, system_instruction):
                final_answer_accumulated.append(token)
                yield {"event": "answer_delta", "data": json.dumps({"delta": token})}
                yield {"event": "token", "data": json.dumps({"token": token})}
            result_holder.tool_results = all_tool_results
            result_holder.final_answer = "".join(final_answer_accumulated)
            return


        enriched_system_prompt = build_react_system_instruction(system_instruction)

        for turn_idx in range(1, self.max_turns + 1):
            yield {
                "event": "status",
                "data": json.dumps({
                    "status": f"ReAct Reasoning (Turn {turn_idx}/{self.max_turns})…",
                    "goal": f"Evaluating next action (Turn {turn_idx})"
                })
            }

            # Generate turn from provider
            turn_output = await provider.generate(turn_messages, enriched_system_prompt)
            react_turn = parse_react_turn(turn_output)

            # Emit thought event if model reasoned
            if react_turn.thought:
                yield {
                    "event": "thought",
                    "data": json.dumps({
                        "react_turn": turn_idx,
                        "thought": react_turn.thought,
                        "action": react_turn.action
                    })
                }

            # If model reached Final Answer (or didn't call any action):
            if react_turn.is_final or not react_turn.action:
                final_text = react_turn.final_answer or react_turn.raw_text
                # Stream the final answer tokens
                words = final_text.split(" ")
                for i, w in enumerate(words):
                    chunk = w + (" " if i < len(words) - 1 else "")
                    final_answer_accumulated.append(chunk)
                    yield {"event": "answer_delta", "data": json.dumps({"delta": chunk})}
                    yield {"event": "token", "data": json.dumps({"token": chunk})}
                    await asyncio.sleep(0.005)
                result_holder.tool_results = all_tool_results
                result_holder.final_answer = "".join(final_answer_accumulated)
                return

            # Model requested an Action
            tool_name = react_turn.action
            tool_args = react_turn.action_input or {}

            yield {
                "event": "tool_start",
                "data": json.dumps({
                    "tool": tool_name,
                    "action": f"ReAct Turn {turn_idx}: {react_turn.thought or f'Executing {tool_name}'}"
                })
            }
            yield {
                "event": "tool_call",
                "data": json.dumps({"tool": tool_name, "arguments": tool_args})
            }

            # Execute tool safely via registry
            if tool_name not in tool_registry._tools:
                res = ToolResult(
                    tool_name=tool_name,
                    status="failed",
                    output=None,
                    latency_ms=1,
                    error=f"Tool '{tool_name}' is not in registered tools: {list(tool_registry._tools.keys())}"
                )
            else:
                res = await tool_registry.execute(tool_name, tool_args)

            all_tool_results.append(res)

            yield {
                "event": "tool_result",
                "data": json.dumps({
                    "tool": tool_name,
                    "status": res.status,
                    "latency_ms": res.latency_ms,
                    "summary": f"{tool_name} {res.status} ({res.latency_ms}ms)"
                })
            }

            # Format observation for next turn
            obs_payload = res.output if res.status == "succeeded" else {"error": res.error or "Action failed"}
            obs_str = json.dumps(obs_payload, indent=2)
            if len(obs_str) > 3000:
                obs_str = obs_str[:3000] + "\n... [Output truncated for context length]"

            # Append assistant step and user observation to conversation history
            turn_messages.append({
                "role": "model",
                "content": f"Thought: {react_turn.thought or 'Executing tool'}\nAction: {tool_name}\nAction Input: {json.dumps(tool_args)}"
            })
            turn_messages.append({
                "role": "user",
                "content": f"Observation:\n{obs_str}"
            })

            # Check if this was the last turn
            if turn_idx == self.max_turns:
                turn_messages.append({
                    "role": "user",
                    "content": "You have reached the maximum allowed ReAct steps. Please synthesize all tool observations above and provide your Final Answer now."
                })
                # Final stream of answer
                async for token in provider.stream_chat(turn_messages, enriched_system_prompt):
                    final_answer_accumulated.append(token)
                    yield {"event": "answer_delta", "data": json.dumps({"delta": token})}
                    yield {"event": "token", "data": json.dumps({"token": token})}
                result_holder.tool_results = all_tool_results
                result_holder.final_answer = "".join(final_answer_accumulated)
                return

        result_holder.tool_results = all_tool_results
        result_holder.final_answer = "".join(final_answer_accumulated)
        return


react_engine = ReActEngine(max_turns=4)
