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

        This function uses different endpoints based on whether streaming is needed:
        - Non-streaming: /search/results endpoint
        - Streaming: /search/stream endpoint

        The streaming endpoint provides real-time updates including search results and report generation.
        This allows the UI to display both the search process and the final report in real-time.

        Args:
            prompt: The search query
            api_key: The API key for authentication
            event_emitter: Optional function to emit events to the client

        Returns:
            The search results and report as a dictionary
        """
        try:
            # 검색 시작 시간 기록
            search_start_time = datetime.now()

            # 초기 reasoning 상태 표시 - 태그를 사용하여 reasoning 메시지 형식 지정
            await event_emitter({
                "type": "chat:completion",
                "data": {
                    "content": f"<details type=\"reasoning\" done=\"false\">\n<summary>Thinking…</summary>\n> ### 검색 시작\n>\n> **검색어:** {prompt}\n>\n> 검색을 시작합니다...\n</details>",
                }
            })

            # If no event emitter is provided, use the non-streaming search results endpoint
            if event_emitter is None:
                async with httpx.AsyncClient(timeout=None) as client:
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}"
                    }

                    # Call the search results endpoint (without final report)
                    response = await client.post(
                        f"{self.valves.api_url}/search/results",
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
                    "sources": [],
                    "final_report": ""  # Store the final report here
                }

                async with httpx.AsyncClient(timeout=None) as client:
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}"
                    }

                    # Call the streaming endpoint (with search results and final report)
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
                                    elif event_type == "summarized_result":
                                        message = f"요약 결과: {data.get('query', '')}의 {data.get('index', 0)}/{data.get('total', 0)} 번째 결과"

                                        # Get the summarized result data
                                        query = data.get("query", "")
                                        original_result = data.get("original_result", {})
                                        summarized_result = data.get("summarized_result", {})
                                        index = data.get("index", 0)
                                        total = data.get("total", 0)
                                        is_additional = data.get("additional", False)

                                        # Format the original result
                                        title = original_result.get("title", "제목 없음")
                                        link = original_result.get("link", "#")

                                        # Format the summarized result for display
                                        summary_message = f"### 검색 결과 요약 ({index}/{total})\n\n"
                                        summary_message += f"**원본:** [{title}]({link})\n\n"
                                        summary_message += f"**요약:**\n{summarized_result.get('content', '')}\n\n"
                                        summary_message += f"**관련성:** {summarized_result.get('relevance', '알 수 없음')}\n\n"

                                        # Stream the summarized result to the UI using chat:completion
                                        await event_emitter({
                                            "type": "chat:completion",
                                            "data": {
                                                "content": f"<details type=\"reasoning\" done=\"false\">\n<summary>Thinking…</summary>\n> {summary_message}\n</details>"
                                            }
                                        })
                                    elif event_type == "evaluation":
                                        message = f"평가: {data.get('query', '')}는 {'충분함' if data.get('sufficient', False) else '불충분함'}"
                                    elif event_type == "report_chunk" or event_type == "report":
                                        message = "보고서 생성 중... (실시간으로 표시됩니다)"
                                    elif event_type == "sources":
                                        message = f"소스 정보: {len(data.get('sources', []))}개 소스 발견"
                                    elif event_type == "search_complete":
                                        message = "검색 및 보고서 생성 완료"
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
                                        results = data.get("results", [])
                                        is_additional = data.get("additional", False)
                                        print_log("info", f"Found {count} results for: {query}")

                                        # Format the search results for display
                                        formatted_results = []
                                        for i, result in enumerate(results[:5]):  # Limit to first 5 results to avoid overwhelming the UI
                                            title = result.get("title", "제목 없음")
                                            link = result.get("link", "#")
                                            snippet = result.get("snippet", "")

                                            formatted_results.append(f"**[{i+1}] {title}**\n링크: {link}\n{snippet}\n")

                                        # Create a message to display the search results
                                        search_results_message = f"### 검색 쿼리: {query}\n\n" + "\n".join(formatted_results)
                                        if len(results) > 5:
                                            search_results_message += f"\n\n... 그 외 {len(results) - 5}개 결과"

                                        # Stream the search results to the UI using chat:completion
                                        await event_emitter({
                                            "type": "chat:completion",
                                            "data": {
                                                "content": f"<details type=\"reasoning\" done=\"false\">\n<summary>Thinking…</summary>\n> {search_results_message}\n</details>"
                                            }
                                        })

                                    elif event_type == "evaluation":
                                        query = data.get("query", "")
                                        sufficient = data.get("sufficient", False)
                                        reasoning = data.get("reasoning", "")
                                        is_additional = data.get("additional", False)
                                        print_log("info", f"Evaluation for {query}: {'Sufficient' if sufficient else 'Insufficient'}")

                                        # Add to search steps
                                        final_results["search_steps"].append({
                                            "query": query,
                                            "results": data.get("results", []),
                                            "sufficient": sufficient,
                                            "reasoning": reasoning
                                        })

                                        # Format the evaluation result for display
                                        eval_message = f"### 검색 결과 평가: {query}\n\n"
                                        eval_message += f"**결과:** {'충분함 ✅' if sufficient else '불충분함 ❌'}\n\n"
                                        eval_message += f"**이유:**\n{reasoning}\n\n"

                                        # Stream the evaluation result to the UI using chat:completion
                                        await event_emitter({
                                            "type": "chat:completion",
                                            "data": {
                                                "content": f"<details type=\"reasoning\" done=\"false\">\n<summary>Thinking…</summary>\n> {eval_message}\n</details>"
                                            }
                                        })

                                    elif event_type == "report_chunk" or event_type == "report":
                                        # Process report chunks and display them in real-time
                                        content = data.get("content", "")
                                        print_log("info", f"Received report chunk: {len(content)} characters")

                                        # Append to the final report
                                        final_results["final_report"] += content

                                        # Stream the report chunk to the UI using chat:completion
                                        await event_emitter({
                                            "type": "chat:completion",
                                            "data": {
                                                "content": f"<details type=\"reasoning\" done=\"false\">\n<summary>Thinking…</summary>\n> {content}\n</details>"
                                            }
                                        })

                                    elif event_type == "sources":
                                        final_results["sources"] = data.get("sources", [])
                                        print_log("info", f"Received {len(final_results['sources'])} sources")

                                    elif event_type == "search_complete":
                                        print_log("info", "Search and report generation completed")

                                        # Send a completion message
                                        await event_emitter({
                                            "type": "chat:completion",
                                            "data": {
                                                "content": "<details type=\"reasoning\" done=\"true\" duration=\"" + str(int((datetime.now() - search_start_time).total_seconds())) + "\">\n<summary>Thought for " + str(int((datetime.now() - search_start_time).total_seconds())) + " seconds</summary>\n> \n> ---\n> \n> **검색 및 보고서 생성이 완료되었습니다.**\n</details>"
                                            }
                                        })

                                        # We don't need this anymore since we're using chat:completion with details tags
                                        # The done=true attribute in the details tag above marks it as complete

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

                # For non-streaming mode only (streaming mode already displays the report in real-time)
                # This code will only run if we're using the non-streaming API endpoint

                # Extract the search results and final report
                search_steps = search_response.get("search_steps", [])
                sources = search_response.get("sources", [])
                final_report = search_response.get("final_report", "")

                # Log the search results
                print_log("info", f"검색 완료: {len(search_steps)} 단계, {len(sources)} 소스, 보고서 길이: {len(final_report)} 자")

                # If we have a final report from the non-streaming API, use it directly
                if final_report:
                    # Create an assistant message with the final report
                    assistant_message = {
                        "role": "assistant",
                        "content": final_report
                    }

                    # Create a new message array with the original messages and the assistant message
                    new_messages = []

                    # Add the original messages
                    for msg in messages:
                        new_messages.append(msg)

                    # Add the assistant message
                    new_messages.append(assistant_message)

                    # Update the body with the new messages
                    body["messages"] = new_messages
                else:
                    # Fallback to the old method if no final report is available
                    # Format sources in a more readable way
                    formatted_sources = []
                    for i, source in enumerate(sources):
                        title = source.get("title", "제목 없음")
                        link = source.get("link", "#")
                        content = source.get("content", "내용 없음")

                        # Truncate content if too long
                        if len(content) > 500:
                            content = content[:500] + "..."

                        formatted_sources.append(f"[{i+1}] {title}\n링크: {link}\n내용: {content}\n")

                    formatted_sources_text = "\n".join(formatted_sources)

                    # Create a system message with search results
                    system_message = {
                        "role": "system",
                        "content": f"""
다음은 Open Search Agent를 통해 검색한 결과입니다. 이 정보를 바탕으로 사용자의 질문에 답변해주세요.

# 사용자 질문
{user_message}

# 검색 쿼리 및 결과
{', '.join([step.get('query', '') for step in search_steps])}

# 검색 소스
{formatted_sources_text}

위 정보를 바탕으로 사용자의 질문에 상세하게 답변해주세요. 소스 정보를 인용하고 출처를 명시해주세요.
답변은 사용자가 이해하기 쉽게 구조화하고, 필요한 경우 마크다운 형식을 사용하여 가독성을 높여주세요.
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
                # For streaming mode, we've already sent the done=True event in the search_complete handler
                await self.emit_status(
                    __event_emitter__,
                    level="status",
                    message="Open Search Agent 검색 및 보고서 생성 완료",
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

