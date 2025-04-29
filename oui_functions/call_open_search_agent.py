"""
title: Open Search Agent Filter
author: hurxxxx
date: 2024-06-01
version: 1.0
license: MIT
description: Filter that connects Open-WebUI to Open-Search-Agent API for enhanced web search capabilities
requirements: requests
"""

from pydantic import BaseModel, Field
from typing import Callable, Awaitable, Any, Optional, List
import json
import httpx
from datetime import datetime
import traceback

from open_webui.utils.misc import get_last_user_message

# 유틸리티 함수
def print_log(level: str, message: str):
    """로그를 출력하는 함수"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level.upper()}] [Open Search Agent] {message}")


class Pipeline:
    class Valves(BaseModel):
        # List target pipeline ids (models) that this filter will be connected to.
        # If you want to connect this filter to all pipelines, you can set pipelines to ["*"]
        pipelines: List[str] = Field(default=["*"])

        # Assign a priority level to the filter pipeline.
        # The priority level determines the order in which the filter pipelines are executed.
        # The lower the number, the higher the priority.
        priority: int = Field(default=0)

        # Open-Search-Agent API settings
        api_url: str = Field(default="http://localhost:8000/open-search-agent")
        api_key: str = Field(default="test_api_key_123")

        # Enable/disable the filter
        status: bool = Field(default=True)

    def __init__(self):
        # Pipeline filters are only compatible with Open WebUI
        self.type = "filter"

        # Set the name of the pipeline
        self.name = "Open Search Agent"

        # Initialize valves
        self.valves = self.Valves()

        print_log("info", f"Filter initialized with API URL: {self.valves.api_url}")

    async def on_startup(self):
        # This function is called when the server is started
        print_log("info", "Filter started")

    async def on_shutdown(self):
        # This function is called when the server is stopped
        print_log("info", "Filter stopped")

    async def emit_status(
        self,
        __event_emitter__: Callable[[dict], Awaitable[None]],
        level: str,
        message: str,
        done: bool = False,
    ):
        """Send status updates to the client"""
        if self.valves.status:
            await __event_emitter__(
                {
                    "type": level,
                    "data": {
                        "description": message,
                        "done": done,
                    },
                }
            )

    async def call_open_search_agent(self, prompt: str, api_key: str) -> dict:
        """Call the Open-Search-Agent API to process a search query"""
        try:
            async with httpx.AsyncClient() as client:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                }

                # Call the search endpoint
                response = await client.post(
                    f"{self.valves.api_url}/search",
                    headers=headers,
                    json={"prompt": prompt},
                    timeout=60.0  # 60 seconds timeout
                )

                if response.status_code == 200:
                    return response.json()
                else:
                    print_log("error", f"API error: {response.status_code} - {response.text}")
                    return {
                        "error": f"API returned status code {response.status_code}",
                        "details": response.text
                    }
        except Exception as e:
            print_log("error", f"Error calling API: {str(e)}")
            return {"error": str(e)}

    async def inlet(
        self,
        body: dict,
        __event_emitter__: Callable[[Any], Awaitable[None]],
        user: Optional[dict] = None,
    ) -> dict:
        """
        Process the incoming chat message and call the Open-Search-Agent API

        Args:
            body: The request body containing the messages
            __event_emitter__: Function to emit events to the client
            user: The user information

        Returns:
            The modified body with the search results
        """
        try:
            # Skip if filter is disabled
            if not self.valves.status:
                return body

            # Skip if this is a title generation request
            if body.get("title", False):
                return body

            # Get the messages from the body
            messages = body.get("messages", [])
            if not messages:
                return body

            # Get the last user message
            user_message = get_last_user_message(messages)
            if not user_message:
                return body

            # Emit status to client
            await self.emit_status(
                __event_emitter__,
                level="status",
                message="Open Search Agent에 검색 요청 중...",
                done=False,
            )

            # Call the Open-Search-Agent API
            try:
                search_response = await self.call_open_search_agent(
                    prompt=user_message,
                    api_key=self.valves.api_key
                )

                # Check if there was an error
                if "error" in search_response:
                    await self.emit_status(
                        __event_emitter__,
                        level="error",
                        message=f"Open Search Agent API 오류: {search_response['error']}",
                        done=True,
                    )
                    return body

                # Extract the search results
                original_prompt = search_response.get("original_prompt", "")
                search_steps = search_response.get("search_steps", [])
                final_report = search_response.get("final_report", "")
                sources = search_response.get("sources", [])

                # Log the search results
                print_log("info", f"검색 완료: {len(search_steps)} 단계, {len(sources)} 소스")

                # Create a system message with the search results
                system_message = {
                    "role": "system",
                    "content": f"""
다음은 Open Search Agent를 통해 검색한 결과입니다:

# 검색 보고서
{final_report}

# 검색 소스
{json.dumps(sources, ensure_ascii=False, indent=2)}

위 정보를 바탕으로 사용자의 질문에 답변해주세요. 소스 정보를 인용하고 출처를 명시해주세요.
"""
                }

                # Create a new message array with the system message and the original user message
                new_messages = [system_message]

                # Add the original messages (except system messages)
                for msg in messages:
                    if msg.get("role") != "system":
                        new_messages.append(msg)

                # Update the body with the new messages
                body["messages"] = new_messages

                # Emit completion status
                await self.emit_status(
                    __event_emitter__,
                    level="status",
                    message="Open Search Agent 검색 완료",
                    done=True,
                )

            except Exception as e:
                print_log("error", f"API 호출 중 오류 발생: {str(e)}")
                await self.emit_status(
                    __event_emitter__,
                    level="error",
                    message=f"Open Search Agent API 호출 중 오류 발생: {str(e)}",
                    done=True,
                )
                # Return the original body if there was an error
                return body



        except Exception as e:
            print_log("error", f"필터 처리 중 오류 발생: {str(e)}")
            print_log("error", f"오류 유형: {type(e).__name__}")

            # 스택 트레이스 출력
            print_log("error", f"스택 트레이스: {''.join(traceback.format_tb(e.__traceback__))}")

            # 오류 상태 전송
            await self.emit_status(
                __event_emitter__,
                level="error",
                message=f"처리 중 오류 발생: {str(e)}",
                done=True,
            )

        return body

