import json
import re
import traceback
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Callable, Awaitable, Any, Optional

from open_webui.models.models import Models
from open_webui.models.users import Users, UserModel
from open_webui.utils.chat import generate_chat_completion
from open_webui.utils.misc import get_last_user_message
from open_webui.models.knowledge import Knowledges
from open_webui.models.files import Files
from open_webui.utils.middleware import chat_web_search_handler


def print_log(level: str, message: str):
    """콘솔에 로그를 출력하는 함수"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level.upper()}] {message}")


def log_error(request_id, e, error_info=None, additional_info=None):
    """오류 정보를 출력하는 함수"""
    print_log("error", f"[{request_id}] 예외 발생: {e}")

    if error_info:
        print_log("error", f"[{request_id}] 상세 오류 정보:\n{error_info}")

    if additional_info:
        print_log("error", f"[{request_id}] 추가 정보: {additional_info}")

    if "'NoneType' object has no attribute 'get'" in str(e):
        print_log(
            "error", f"[{request_id}] NoneType 오류 특별 진단 시작 ---------------"
        )
        stack_trace = traceback.format_exc()
        frame_info = []
        for i, line in enumerate(stack_trace.splitlines()):
            if "File " in line:
                frame_info.append(line.strip())

        if frame_info:
            print_log("error", f"[{request_id}] 호출 스택 정보:")
            for frame in frame_info:
                print_log("error", f"[{request_id}]   {frame}")

        print_log(
            "error", f"[{request_id}] NoneType 오류 특별 진단 종료 ---------------"
        )


def parse_json_content(content: str) -> Optional[dict]:
    """JSON 문자열을 파싱하여 딕셔너리로 변환"""

    def try_load_json(json_str: str) -> Optional[dict]:
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return None

    content = content.strip()

    if content.lower() == "none":
        return None

    if content.startswith("{") and content.endswith("}"):
        parsed_data = try_load_json(content)
        if parsed_data is not None:
            return parsed_data

        content_single_to_double = content.replace("'", '"')
        parsed_data = try_load_json(content_single_to_double)
        if parsed_data is not None:
            return parsed_data

        return None

    match = re.search(r"\{.*?\}", content, flags=re.DOTALL)
    if not match:
        return None

    json_str = match.group(0)

    parsed_data = try_load_json(json_str)
    if parsed_data is not None:
        return parsed_data

    json_str_converted = json_str.replace("'", '"')
    parsed_data = try_load_json(json_str_converted)
    if parsed_data is not None:
        return parsed_data

    return None


class Filter:
    class Valves(BaseModel):
        status: bool = Field(default=True)
        auto_search_mode: bool = Field(default=False)
        plan_model: str = Field(default="gpt-4.1-mini")

    def __init__(self):
        self.valves = self.Valves()
        print_log("info", "Auto Knowledge Selection 필터 초기화됨")

    async def emit_status(
        self,
        __event_emitter__: Callable[[dict], Awaitable[None]],
        level: str,
        message: str = "",
        done: bool = False,
    ):
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

    async def select_knowledge_base(
        self, body: dict, __user__: Optional[dict]
    ) -> Optional[dict]:
        """사용자의 메시지를 바탕으로 적절한 Knowledge Base를 선택"""
        messages = body["messages"] 
        user_message = get_last_user_message(messages)

        all_knowledge_bases = Knowledges.get_knowledge_bases_by_user_id(
            __user__.get("id"), "read"
        )

        knowledge_bases_list = "\n\n".join(
            [
                f"--- Knowledge Base {index + 1} ---\n"
                f"ID: {getattr(knowledge_base, 'id', 'Unknown')}\n"
                f"Name: {getattr(knowledge_base, 'name', 'Unknown')}\n"
                f"Description: {getattr(knowledge_base, 'description', 'Unknown')}"
                for index, knowledge_base in enumerate(all_knowledge_bases)
            ]
        )

        system_prompt = f"""You are a system that selects the most appropriate knowledge bases for the user's query.
Below is a list of knowledge bases accessible by the user. 
Based on the user's prompt, return the 1-3 most relevant knowledge bases as an array. 
If no relevant knowledge bases are applicable, return an "None" without any explanation.

Available knowledge bases:
{knowledge_bases_list}

Return the result in the following JSON format (no extra keys, no explanations):
{{
    "selected_knowledge_bases": 
        [
            {{
                "id": <KnowledgeBaseID>,
                "name": <KnowledgeBaseName>
            }},
            ...
        ]
}}
"""

        prompt = (
            "History:\n"
            + "\n".join(
                [
                    f"{message['role'].upper()}: \"\"\"{message['content']}\"\"\""
                    for message in messages[::-1][:4]
                ]
            )
            + f"\nUser query: {user_message}"
        )

        return {
            "system_prompt": system_prompt,
            "prompt": prompt,
            "model": self.valves.plan_model,
        }

    async def determine_web_search_needed(
        self, body: dict, __user__: Optional[dict]
    ) -> Optional[dict]:
        """사용자의 메시지를 바탕으로 웹 검색 필요 여부를 판단"""
        messages = body["messages"]
        user_message = get_last_user_message(messages)

        system_prompt = """You are a system that determines if a web search is needed for the user's query.

Consider the following when making your decision:
1. If the query relates to real-time or up-to-date information, including recurring events 
   (e.g., a presidential inauguration, annual shareholder meetings, quarterly earnings reports, 
   product launches, or company announcements), enable a web search to ensure the most recent 
   occurrence is addressed.

2. If the query is not about historical facts, assume most questions benefit from incorporating 
   the latest information available through a web search.

3. Particularly for questions regarding business or economic topics—such as company or 
   industry trends, corporate information, related public figures, government policies, 
   taxes, new technologies, and other fast-changing subjects—web search is strongly recommended 
   to ensure accuracy and freshness of data.

4. For general or everyday prompts that may require current information (e.g., weather updates, recent news, live events), enable a web search.

5. Strive to make human-like judgments to ensure your decision aligns with the user's intent 
   and the context of the question.

6. If the user's query is not clear, return "None" without any explanation.

Return the result in the following JSON format:
{
    "web_search_enabled": boolean
}"""

        prompt = (
            "History:\n"
            + "\n".join(
                [
                    f"{message['role'].upper()}: \"\"\"{message['content']}\"\"\""
                    for message in messages[::-1][:4]
                ]
            )
            + f"\nUser query: {user_message}"
        )

        return {
            "system_prompt": system_prompt,
            "prompt": prompt,
            "model": self.valves.plan_model,
        }

    async def determine_simple_query(
        self, body: dict, __user__: Optional[dict]
    ) -> Optional[dict]:
        """사용자의 메시지가 단순 질문인지 판단하는 함수"""
        messages = body["messages"]
        user_message = get_last_user_message(messages)

        system_prompt = """당신은 사용자의 질문이 단순한 질문인지 아닌지를 판단하는 시스템입니다.

다음과 같은 경우를 단순 질문으로 간주합니다:
1. 인사말 (예: "안녕하세요", "좋은 아침입니다")
2. 일반적인 상식 질문 (예: "물은 몇 도에서 끓나요?")
3. 기본적인 수학 문제 (예: "2 + 2는 얼마인가요?")
4. 농담이나 유머 (예: "재미있는 농담 해주세요")
5. 단순한 작문 요청 (예: "사과에 대한 짧은 글을 써주세요")
6. 일상적인 대화 (예: "오늘 기분이 어떠세요?")
7. 기본적인 정의나 개념 질문 (예: "민주주의란 무엇인가요?")

다음과 같은 경우는 단순 질문이 아닙니다:
1. 특정 분야의 전문적인 지식이 필요한 질문
2. 최신 정보나 데이터가 필요한 질문
3. 복잡한 분석이나 추론이 필요한 질문
4. 특정 문서나 자료에 대한 참조가 필요한 질문
5. 기술적인 문제해결이 필요한 질문

결과를 다음 JSON 형식으로 반환하세요:
{
    "is_simple_query": boolean,
    "reason": "판단 이유를 간단히 설명"
}"""

        prompt = (
            "History:\n"
            + "\n".join(
                [
                    f"{message['role'].upper()}: \"\"\"{message['content']}\"\"\""
                    for message in messages[::-1][:4]
                ]
            )
            + f"\nUser query: {user_message}"
        )

        return {
            "system_prompt": system_prompt,
            "prompt": prompt,
            "model": self.valves.plan_model,
        }

    async def inlet(
        self,
        body: dict,
        __event_emitter__: Callable[[Any], Awaitable[None]],
        __request__: Any,
        __user__: Optional[dict] = None,
        __model__: Optional[dict] = None,
    ) -> dict:
        request_id = (
            datetime.now().strftime("%Y%m%d%H%M%S") + "_" + str(id(__request__))[-6:]
        )
        print_log("info", f"[{request_id}] inlet 함수 시작")

        try:
            if __user__ is None:
                user_data = {}
                user = None
            else:
                user_data = __user__.copy()
                user_data.update(
                    {
                        "profile_image_url": "",
                        "last_active_at": 0,
                        "updated_at": 0,
                        "created_at": 0,
                    }
                )
                user = Users.get_user_by_id(__user__["id"])

            user_object = UserModel(**user_data)

            # 0) 단순 질문 여부 판단
            print_log("info", f"[{request_id}] 단순 질문 여부 판단 시작")
            simple_query_plan = await self.determine_simple_query(body, __user__)
            if simple_query_plan is None:
                print_log(
                    "warning",
                    f"[{request_id}] determine_simple_query 결과가 None입니다",
                )
                raise ValueError("determine_simple_query result is None")

            simple_query_payload = {
                "model": simple_query_plan["model"],
                "messages": [
                    {"role": "system", "content": simple_query_plan["system_prompt"]},
                    {"role": "user", "content": simple_query_plan["prompt"]},
                ],
                "stream": False,
            }

            print_log("info", f"[{request_id}] LLM 호출: 단순 질문 여부 판단")
            simple_query_response = await generate_chat_completion(
                request=__request__, form_data=simple_query_payload, user=user
            )

            if simple_query_response is None:
                print_log(
                    "warning", f"[{request_id}] simple_query_response가 None입니다"
                )
                is_simple_query = False
            else:
                simple_query_content = simple_query_response["choices"][0]["message"][
                    "content"
                ]
                simple_query_result = parse_json_content(simple_query_content)

                if simple_query_result is None:
                    print_log(
                        "warning",
                        f"[{request_id}] simple_query_result 파싱 결과가 None입니다",
                    )
                    is_simple_query = False
                else:
                    is_simple_query = simple_query_result.get("is_simple_query", False)
                    reason = simple_query_result.get("reason", "")
                    print_log(
                        "info",
                        f"[{request_id}] 단순 질문 판단 결과: {is_simple_query}, 이유: {reason}",
                    )

            if is_simple_query:
                print_log(
                    "info",
                    f"[{request_id}] 단순 질문으로 판단되어 Knowledge Base 선택 과정을 건너뜁니다",
                )
                selected_knowledge_bases = []
                body["files"] = []
                body["model"] = self.valves.plan_model
                basic_model = Models.get_model_by_id(self.valves.plan_model)
                if "metadata" not in body:
                    body["metadata"] = {}
                if basic_model:
                    body["metadata"]["model"] = basic_model.model_dump()
                return body
            else:
                # 1) Knowledge Base 선택
                print_log("info", f"[{request_id}] Knowledge Base 선택 시작")
                kb_plan = await self.select_knowledge_base(body, __user__)
                if kb_plan is None:
                    print_log(
                        "warning",
                        f"[{request_id}] select_knowledge_base 결과가 None입니다",
                    )
                    raise ValueError("select_knowledge_base result is None")

                kb_payload = {
                    "model": kb_plan["model"],
                    "messages": [
                        {"role": "system", "content": kb_plan["system_prompt"]},
                        {"role": "user", "content": kb_plan["prompt"]},
                    ],
                    "stream": False,
                }

                print_log("info", f"[{request_id}] LLM 호출: Knowledge Base 선택")
                kb_response = await generate_chat_completion(
                    request=__request__, form_data=kb_payload, user=user
                )

                if kb_response is None:
                    print_log("warning", f"[{request_id}] kb_response가 None입니다")
                    kb_content = ""
                else:
                    kb_content = (
                        kb_response["choices"][0]["message"]["content"]
                        if kb_response
                        else ""
                    )

                if kb_content == "None":
                    selected_knowledge_bases = []
                    print_log(
                        "info", f"[{request_id}] 선택된 Knowledge Base가 없습니다."
                    )
                else:
                    try:
                        kb_result = parse_json_content(kb_content)

                        if kb_result is None:
                            print_log(
                                "warning",
                                f"[{request_id}] kb_result 파싱 결과가 None입니다",
                            )
                            selected_knowledge_bases = []
                        else:
                            selected_knowledge_bases = kb_result.get(
                                "selected_knowledge_bases", []
                            )
                    except Exception as e:
                        error_info = traceback.format_exc()
                        log_error(
                            request_id,
                            e,
                            error_info,
                            f"파싱 대상 문자열: {kb_content[:200]}...",
                        )
                        selected_knowledge_bases = []

            # 2) 웹 검색 필요 여부 판단
            if self.valves.auto_search_mode:
                print_log("info", f"[{request_id}] 웹 검색 필요 여부 판단 시작")
                ws_plan = await self.determine_web_search_needed(body, __user__)
                if ws_plan is None:
                    print_log(
                        "warning",
                        f"[{request_id}] determine_web_search_needed 결과가 None입니다",
                    )
                    raise ValueError("determine_web_search_needed result is None")

                ws_payload = {
                    "model": ws_plan["model"],
                    "messages": [
                        {"role": "system", "content": ws_plan["system_prompt"]},
                        {"role": "user", "content": ws_plan["prompt"]},
                    ],
                    "stream": False,
                }

                print_log("info", f"[{request_id}] LLM 호출: 웹 검색 필요 여부 판단")
                ws_response = await generate_chat_completion(
                    request=__request__, form_data=ws_payload, user=user
                )

                if ws_response is None:
                    print_log("warning", f"[{request_id}] ws_response가 None입니다")
                    ws_content = ""
                else:
                    ws_content = (
                        ws_response["choices"][0]["message"]["content"]
                        if ws_response
                        else ""
                    )

                ws_result = parse_json_content(ws_content)

                if ws_result is None:
                    print_log(
                        "warning", f"[{request_id}] ws_result 파싱 결과가 None입니다"
                    )
                    web_search_enabled = False
                else:
                    web_search_enabled = ws_result.get("web_search_enabled", False)

                if isinstance(web_search_enabled, str):
                    web_search_enabled = web_search_enabled.lower() in ["true", "yes"]

                if web_search_enabled:
                    print_log("info", f"[{request_id}] 웹 검색 실행")
                    await chat_web_search_handler(
                        __request__,
                        body,
                        {"__event_emitter__": __event_emitter__},
                        user_object,
                    )
                else:
                    print_log("info", f"[{request_id}] 웹 검색이 필요하지 않습니다.")

            # 3) Knowledge Base 처리
            print_log(
                "info",
                f"[{request_id}] 선택된 Knowledge Base 처리 시작, 개수: {len(selected_knowledge_bases)}",
            )
            selected_kb_names = []
            for selected_knowledge_base in selected_knowledge_bases:
                kb_id = selected_knowledge_base.get("id")
                kb_name = selected_knowledge_base.get("name")

                if kb_id and kb_name:
                    selected_kb_names.append(kb_name)
                    selected_knowledge_base_info = Knowledges.get_knowledge_by_id(kb_id)

                    if selected_knowledge_base_info:
                        if (
                            not hasattr(selected_knowledge_base_info, "data")
                            or selected_knowledge_base_info.data is None
                        ):
                            print_log(
                                "warning",
                                f"[{request_id}] selected_knowledge_base_info.data가 없거나 None입니다",
                            )
                            continue

                        knowledge_file_ids = selected_knowledge_base_info.data.get(
                            "file_ids", []
                        )
                        knowledge_files = Files.get_file_metadatas_by_ids(
                            knowledge_file_ids
                        )
                        knowledge_dict = selected_knowledge_base_info.model_dump()
                        knowledge_dict["files"] = [
                            file.model_dump() for file in knowledge_files
                        ]
                        knowledge_dict["type"] = "collection"

                        if "files" not in body:
                            body["files"] = []
                        body["files"].append(knowledge_dict)

            if selected_kb_names:
                kb_names_str = ", ".join(selected_kb_names)
                print_log(
                    "info", f"[{request_id}] 선택된 Knowledge Base 이름: {kb_names_str}"
                )
                await self.emit_status(
                    __event_emitter__,
                    level="status",
                    message=f"Matching knowledge bases found: {kb_names_str}",
                    done=True,
                )

        except Exception as e:
            error_info = traceback.format_exc()
            log_error(request_id, e, error_info)

            await self.emit_status(
                __event_emitter__,
                level="status",
                message=f"추가 할 지식베이스가 없습니다.",
                done=True,
            )

        context_message = {
            "role": "system",
            "content": (
                "You are a multidisciplinary expert with contextual adaptation capabilities. You possess deep expertise in the following fields: project management, psychology, economics, design, marketing, and engineering. You are able to use this knowledge in an integrated manner while adapting your approach to the specific needs of each request.\n\n"
                "The user is seeking high-level expertise to answer their questions or help them with their professional and personal projects. Each request may require a different level of depth, communication style, and analytical framework.\n\n"
                "Basic Structure for All Responses:\n"
                "1. Begin by precisely understanding the request, asking clarifying questions if necessary.\n"
                "2. Adapt your depth level according to the context (quick response or in-depth analysis).\n"
                "3. Use clear and accessible language, avoiding corporate jargon unless relevant.\n"
                "4. Check the logical consistency of your response before finalizing it.\n"
                "5. End with a bullet-point summary of the essential elements to remember.\n\n"
                "Analytical Approach (to apply as relevant):\n"
                "- Leverage your interdisciplinary expertise (PM, psychology, economics, design, marketing, engineering).\n"
                "- Cite relevant references when they strengthen your point (e.g., Ries, 2011; McKinsey, 2021).\n"
                "- After each analysis, check your logic against recognized theoretical frameworks (Gibson, 2022).\n"
                "- Highlight any contradictions or tensions in the analysis.\n"
                "- Use recognized analytical frameworks when appropriate (RICE, OKRs, Double Diamond, etc.).\n"
                "- Identify potentially problematic assumptions using data or logic.\n\n"
                "Response Enrichment (to use selectively):\n"
                "- Illustrate your points with concrete and concise anecdotes.\n"
                "- Integrate relevant academic knowledge by explaining it simply.\n"
                "- Propose alternative scenario simulations when it helps decision-making.\n"
                "- Present the advantages and disadvantages of different options when a decision needs to be made.\n"
                "- Structure complex points in narrative form to facilitate understanding.\n\n"
                "Contextual Adaptation:\n"
                "- Keep in memory the objectives and constraints mentioned previously in the conversation.\n"
                "- If the user seems stressed, acknowledge it and suggest concrete steps to move forward.\n"
                "- Maintain consistency in the terminology used unless requested otherwise.\n"
                "- Follow a continuous improvement process by taking into account user feedback.\n"
                "- Keep track of recurring topics to allow for further exploration later.\n\n"
                "Output Format:\n"
                "1. A direct answer to the main question\n"
                "2. A structured analysis using relevant techniques\n"
                "3. Concrete examples or illustrations if appropriate\n"
                "4. A final bullet-point summary\n"
                "5. Follow-up or further exploration suggestions if relevant\n\n"
                "**IMPORTANT: Additionally, please respond in the language used by the user in their input.**\n\n"
            ),
        }

        body.setdefault("messages", []).insert(0, context_message)
        print_log("info", f"[{request_id}] inlet 함수 종료")

        await self.emit_status(
            __event_emitter__,
            level="status",
            message="답변을 준비중입니다. 잠시만 기다려 주세요",
            done=False,
        )
        return body

    async def outlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __event_emitter__: Callable[[Any], Awaitable[None]] = None,
    ) -> dict:
        await self.emit_status(
            __event_emitter__,
            level="status",
            done=True,
        )
