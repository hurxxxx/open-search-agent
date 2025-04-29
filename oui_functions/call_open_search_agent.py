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
from typing import Callable, Awaitable, Any, List
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


class Filter:
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

    async def call_open_search_agent(self, prompt: str, api_key: str, event_emitter=None) -> dict:
        """
        Call the Open-Search-Agent API to process a search query

        Args:
            prompt: The search query
            api_key: The API key for authentication
            event_emitter: Optional function to emit events to the client

        Returns:
            The search results as a dictionary
        """
        try:
            # If no event emitter is provided, use the regular search endpoint
            if event_emitter is None:
                async with httpx.AsyncClient(timeout=None) as client:
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}"
                    }

                    # Call the search endpoint
                    response = await client.post(
                        f"{self.valves.api_url}/search",
                        headers=headers,
                        json={"prompt": prompt}
                    )

                    if response.status_code == 200:
                        return response.json()
                    else:
                        print_log("error", f"API error: {response.status_code} - {response.text}")
                        return {
                            "error": f"API returned status code {response.status_code}",
                            "details": response.text
                        }
            # If an event emitter is provided, use the streaming endpoint
            else:
                # Final results to return
                final_results = {
                    "original_prompt": prompt,
                    "search_steps": [],
                    "final_report": "",
                    "sources": []
                }

                async with httpx.AsyncClient(timeout=None) as client:
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}"
                    }

                    # Call the streaming search endpoint
                    async with client.stream(
                        "POST",
                        f"{self.valves.api_url}/search/stream",
                        headers=headers,
                        json={"prompt": prompt}
                    ) as response:
                        if response.status_code != 200:
                            error_text = await response.text()
                            print_log("error", f"API error: {response.status_code} - {error_text}")
                            return {
                                "error": f"API returned status code {response.status_code}",
                                "details": error_text
                            }

                        # Process the streaming response
                        buffer = ""
                        async for chunk in response.aiter_text():
                            buffer += chunk

                            # Process complete lines in the buffer
                            while "\n" in buffer:
                                line, buffer = buffer.split("\n", 1)
                                if not line.strip():
                                    continue

                                try:
                                    event_data = json.loads(line)
                                    event_type = event_data.get("event")
                                    data = event_data.get("data", {})

                                    # Create a user-friendly message based on the event type
                                    message = ""
                                    if event_type == "search_start":
                                        message = f"검색 시작: {data.get('prompt', '')[:50]}..."
                                    elif event_type == "decomposed_queries":
                                        queries = data.get("queries", [])
                                        message = f"검색 쿼리 분해: {len(queries)}개의 쿼리로 분해됨"
                                    elif event_type == "search_query":
                                        message = f"검색 중: {data.get('query', '')}"
                                    elif event_type == "search_results":
                                        message = f"검색 결과: {data.get('query', '')}에 대해 {data.get('count', 0)}개 결과 발견"
                                    elif event_type == "summarize_progress":
                                        message = f"요약 중: {data.get('query', '')}의 결과 {data.get('current', 0)}/{data.get('total', 0)}"
                                    elif event_type == "summarize_complete":
                                        message = f"요약 완료: {data.get('query', '')}의 {data.get('count', 0)}개 결과"
                                    elif event_type == "evaluation":
                                        message = f"평가: {data.get('query', '')}는 {'충분함' if data.get('sufficient', False) else '불충분함'}"
                                    elif event_type == "report_chunk":
                                        message = "보고서 생성 중..."
                                    elif event_type == "sources":
                                        message = f"소스 정보: {len(data.get('sources', []))}개 소스 발견"
                                    elif event_type == "search_complete":
                                        message = "검색 완료"
                                    elif event_type == "error":
                                        message = f"오류: {data.get('message', '')}"
                                    else:
                                        message = f"{event_type}: {json.dumps(data, ensure_ascii=False)[:50]}..."

                                    # Forward the event to the client
                                    await event_emitter({
                                        "type": "status",
                                        "data": {
                                            "description": f"Open Search Agent: {message}",
                                            "done": event_type == "search_complete"
                                        }
                                    })

                                    # Process different event types
                                    if event_type == "search_start":
                                        print_log("info", f"Search started for: {data.get('prompt')}")

                                    elif event_type == "decomposed_queries":
                                        queries = data.get("queries", [])
                                        print_log("info", f"Decomposed into {len(queries)} queries")

                                    elif event_type == "search_query":
                                        query = data.get("query", "")
                                        print_log("info", f"Searching for: {query}")

                                    elif event_type == "search_results":
                                        count = data.get("count", 0)
                                        query = data.get("query", "")
                                        print_log("info", f"Found {count} results for: {query}")

                                    elif event_type == "evaluation":
                                        query = data.get("query", "")
                                        sufficient = data.get("sufficient", False)
                                        print_log("info", f"Evaluation for {query}: {'Sufficient' if sufficient else 'Insufficient'}")

                                        # Add to search steps
                                        final_results["search_steps"].append({
                                            "query": query,
                                            "results": data.get("results", []),
                                            "sufficient": sufficient,
                                            "reasoning": data.get("reasoning", "")
                                        })

                                    elif event_type == "report_chunk":
                                        final_results["final_report"] += data.get("content", "")

                                    elif event_type == "sources":
                                        final_results["sources"] = data.get("sources", [])
                                        print_log("info", f"Received {len(final_results['sources'])} sources")

                                    elif event_type == "search_complete":
                                        print_log("info", "Search completed")

                                    elif event_type == "error":
                                        print_log("error", f"Error from Open Search Agent: {data.get('message')}")
                                        return {"error": data.get("message")}

                                except json.JSONDecodeError:
                                    print_log("error", f"Failed to parse event: {line}")
                                except Exception as e:
                                    print_log("error", f"Error processing event: {str(e)}")

                return final_results

        except Exception as e:
            print_log("error", f"Error calling API: {str(e)}")
            return {"error": str(e)}

    async def inlet(
        self,
        body: dict,
        __event_emitter__: Callable[[Any], Awaitable[None]],
    ) -> dict:
        """
        Process the incoming chat message and call the Open-Search-Agent API

        Args:
            body: The request body containing the messages
            __event_emitter__: Function to emit events to the client

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

            # Call the Open-Search-Agent API with streaming
            try:
                # Call the API with the event emitter to get streaming updates
                search_response = await self.call_open_search_agent(
                    prompt=user_message,
                    api_key=self.valves.api_key,
                    event_emitter=__event_emitter__
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

