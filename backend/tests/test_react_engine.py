import pytest
import json
import asyncio
from typing import AsyncGenerator, Dict, Any, List, Optional

from app.services.agent.react_engine import (
    parse_react_turn,
    build_react_system_instruction,
    ReActEngine,
    ReActResult,
    ReActTurn
)
from app.services.llm.base import BaseLLMProvider
from app.services.tools.tool_registry import ToolResult

def test_parse_react_turn_standard_json():
    text = (
        "Thought: We need to inspect the project directory structure.\n"
        "Action: project_inspector\n"
        "Action Input: {\"subpath\": \"backend/app\"}"
    )
    turn = parse_react_turn(text)
    assert turn.is_final is False
    assert turn.action == "project_inspector"
    assert turn.action_input == {"subpath": "backend/app"}
    assert turn.thought == "We need to inspect the project directory structure."

def test_parse_react_turn_markdown_codeblock():
    text = (
        "Thought: Let me search for authentication functions.\n"
        "Action: file_searcher\n"
        "Action Input: ```json\n"
        "{\n"
        '  "query": "def login",\n'
        '  "file_pattern": "*.py"\n'
        "}\n"
        "```"
    )
    turn = parse_react_turn(text)
    assert turn.is_final is False
    assert turn.action == "file_searcher"
    assert turn.action_input == {"query": "def login", "file_pattern": "*.py"}

def test_parse_react_turn_raw_string_fallback():
    text = (
        "Thought: Running pytest health suite.\n"
        "Action: test_runner\n"
        "Action Input: tests/test_health.py"
    )
    turn = parse_react_turn(text)
    assert turn.is_final is False
    assert turn.action == "test_runner"
    assert turn.action_input == {"test_target": "tests/test_health.py"}

def test_parse_react_turn_final_answer():
    text = (
        "Thought: I have verified all 90 backend tests.\n"
        "Final Answer: All 90 tests passed with 100% pass rate. System is fully operational."
    )
    turn = parse_react_turn(text)
    assert turn.is_final is True
    assert turn.final_answer == "All 90 tests passed with 100% pass rate. System is fully operational."

def test_parse_react_turn_direct_answer():
    text = "Hello! I am DotMind, your personal mobile AI agent. How can I assist you today?"
    turn = parse_react_turn(text)
    assert turn.is_final is True
    assert "DotMind" in turn.final_answer

def test_build_react_system_instruction():
    prompt = build_react_system_instruction("Base prompt")
    assert "--- AVAILABLE WORKSPACE TOOLS (REACT REASONING ENGINE) ---" in prompt
    assert "test_runner" in prompt
    assert "file_reader" in prompt
    assert "github_researcher" in prompt
    assert "Action: <One of the registered tool names above>" in prompt
    assert "Final Answer:" in prompt

class MultiStepMockProvider(BaseLLMProvider):
    def __init__(self, responses: List[str]):
        self.responses = list(responses)
        self.call_idx = 0

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        system_instruction: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        for word in ["Final", " answer", " streamed", " successfully."]:
            yield word

    async def generate(
        self,
        messages: List[Dict[str, Any]],
        system_instruction: Optional[str] = None
    ) -> str:
        if self.call_idx < len(self.responses):
            res = self.responses[self.call_idx]
            self.call_idx += 1
            return res
        return "Final Answer: Done."

@pytest.mark.asyncio
async def test_react_engine_multi_turn_execution():
    responses = [
        # Turn 1: Call test_runner
        (
            "Thought: I must verify health endpoints first.\n"
            "Action: test_runner\n"
            "Action Input: {\"test_target\": \"tests/test_health.py\"}"
        ),
        # Turn 2: Synthesize and complete
        (
            "Thought: Tests passed cleanly. I will now respond.\n"
            "Final Answer: The health tests executed successfully."
        )
    ]
    provider = MultiStepMockProvider(responses)
    engine = ReActEngine(max_turns=3)
    holder = ReActResult()

    events = []
    async for event in engine.execute_react_loop(
        provider=provider,
        messages=[{"role": "user", "content": "Check health tests"}],
        system_instruction="You are DotMind.",
        result_holder=holder
    ):
        events.append(event)

    event_types = [e["event"] for e in events]
    assert "status" in event_types
    assert "thought" in event_types
    assert "tool_start" in event_types
    assert "tool_call" in event_types
    assert "tool_result" in event_types
    assert "token" in event_types

    assert len(holder.tool_results) == 1
    assert holder.tool_results[0].tool_name == "test_runner"
    assert "health tests executed" in holder.final_answer

@pytest.mark.asyncio
async def test_react_engine_unknown_tool_graceful():
    responses = [
        (
            "Thought: Calling nonexistent tool.\n"
            "Action: non_existent_tool_xyz\n"
            "Action Input: {}"
        ),
        (
            "Thought: Tool was not found, explaining to user.\n"
            "Final Answer: That tool is not supported in this environment."
        )
    ]
    provider = MultiStepMockProvider(responses)
    engine = ReActEngine(max_turns=2)
    holder = ReActResult()

    events = []
    async for event in engine.execute_react_loop(
        provider=provider,
        messages=[{"role": "user", "content": "Run xyz"}],
        system_instruction="You are DotMind.",
        result_holder=holder
    ):
        events.append(event)

    assert len(holder.tool_results) == 1
    assert holder.tool_results[0].status == "failed"
    assert "not in registered tools" in holder.tool_results[0].error
    assert "not supported" in holder.final_answer

@pytest.mark.asyncio
async def test_react_engine_max_turns_enforcement():
    # Model keeps calling tools indefinitely
    responses = [
        "Thought: Step 1.\nAction: project_inspector\nAction Input: {}",
        "Thought: Step 2.\nAction: project_inspector\nAction Input: {}",
        "Thought: Step 3.\nAction: project_inspector\nAction Input: {}"
    ]
    provider = MultiStepMockProvider(responses)
    engine = ReActEngine(max_turns=2)
    holder = ReActResult()

    events = []
    async for event in engine.execute_react_loop(
        provider=provider,
        messages=[{"role": "user", "content": "Inspect forever"}],
        system_instruction="You are DotMind.",
        result_holder=holder
    ):
        events.append(event)

    assert len(holder.tool_results) == 2
    assert "Final answer streamed" in holder.final_answer
