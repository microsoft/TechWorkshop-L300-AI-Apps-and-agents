import asyncio
import logging
import os
from collections.abc import AsyncIterable
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Any, Literal
import httpx
import openai
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from pydantic import BaseModel
from semantic_kernel.agents import ChatCompletionAgent, ChatHistoryAgentThread
from semantic_kernel.connectors.ai.open_ai import (
    AzureChatCompletion,
    OpenAIChatCompletion,
    OpenAIChatPromptExecutionSettings,
)
from semantic_kernel.contents import (
    FunctionCallContent,
    FunctionResultContent,
    StreamingChatMessageContent,
    StreamingTextContent,
)
from semantic_kernel.functions import KernelArguments, kernel_function

if TYPE_CHECKING:
    from semantic_kernel.connectors.ai.chat_completion_client_base import (
        ChatCompletionClientBase,
    )
    from semantic_kernel.contents import ChatMessageContent

logger = logging.getLogger(__name__)
load_dotenv()
# region Chat Service Configuration


class ChatServices(str, Enum):
    """Enum for supported chat completion services."""

    AZURE_OPENAI = 'azure_openai'
    OPENAI = 'openai'


service_id = 'default'


def get_chat_completion_service(
    service_name: ChatServices,
) -> 'ChatCompletionClientBase':
    """Return an appropriate chat completion service based on the service name.

    Args:
        service_name (ChatServices): Service name.

    Returns:
        ChatCompletionClientBase: Configured chat completion service.

    Raises:
        ValueError: If the service name is not supported or required environment variables are missing.
    """
    if service_name == ChatServices.AZURE_OPENAI:
        return _get_azure_openai_chat_completion_service()
    if service_name == ChatServices.OPENAI:
        return _get_openai_chat_completion_service()
    raise ValueError(f'Unsupported service name: {service_name}')


def _get_azure_openai_chat_completion_service() -> AzureChatCompletion:
    """Return Azure OpenAI chat completion service with managed identity.

    Returns:
        AzureChatCompletion: The configured Azure OpenAI service.
    """
    endpoint = os.getenv('gpt_endpoint')
    deployment_name = os.getenv('gpt_deployment')
    api_version = os.getenv('gpt_api_version')
    api_key = os.getenv('gpt_api_key')

    if not endpoint:
        raise ValueError("gpt_endpoint is required")
    if not deployment_name:
        raise ValueError("gpt_deployment is required")
    if not api_version:
        raise ValueError("gpt_api_version is required")

    # Use managed identity if no API key is provided
    if not api_key:
        # Create Azure credential for managed identity
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        
        # Create OpenAI client with managed identity
        async_client = openai.AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
            api_version=api_version,
        )
        
        return AzureChatCompletion(
            service_id=service_id,
            deployment_name=deployment_name,
            async_client=async_client,
        )
    else:
        # Fallback to API key authentication for local development
        return AzureChatCompletion(
            service_id=service_id,
            deployment_name=deployment_name,
            endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )


def _get_openai_chat_completion_service() -> OpenAIChatCompletion:
    """Return OpenAI chat completion service.

    Returns:
        OpenAIChatCompletion: Configured OpenAI service.
    """
    return OpenAIChatCompletion(
        service_id=service_id,
        ai_model_id=os.getenv('OPENAI_MODEL_ID'),
        api_key=os.getenv('OPENAI_API_KEY'),
    )


# endregion
# region Response Format


class ResponseFormat(BaseModel):
    """A Response Format model to direct how the model should respond."""

    status: Literal['input_required', 'completed', 'error'] = 'input_required'
    message: str


# endregion
# region Semantic Kernel Agent


class SemanticKernelProductManagementAgent:
    """Wraps Semantic Kernel-based agents to handle Zava product management tasks."""

    agent: ChatCompletionAgent
    thread: ChatHistoryAgentThread = None
    SUPPORTED_CONTENT_TYPES = ['text', 'text/plain']

    def __init__(self):
        # Configure the chat completion service explicitly
        chat_service = get_chat_completion_service(ChatServices.AZURE_OPENAI)

        # Define the main ProductManagerAgent to delegate tasks to the appropriate agents
        self.agent = ChatCompletionAgent(
            service=chat_service,
            name='ProductManagerAgent',
            instructions=(
                "Your role is to carefully analyze the user's request and respond as best as you can. "
                'Your primary goal is precise and efficient delegation to ensure customers and employees receive accurate and specialized '
                'assistance promptly.'
            ),
            plugins=[],
            arguments=KernelArguments(
                settings=OpenAIChatPromptExecutionSettings(
                    response_format=ResponseFormat,
                )
            ),
        )

    async def invoke(self, user_input: str, session_id: str) -> dict[str, Any]:
        """Handle synchronous tasks (like tasks/send).

        Args:
            user_input (str): User input message.
            session_id (str): Unique identifier for the session.

        Returns:
            dict: A dictionary containing the content, task completion status,
            and user input requirement.
        """
        await self._ensure_thread_exists(session_id)

        # Use SK's get_response for a single shot
        response = await self.agent.get_response(
            messages=user_input,
            thread=self.thread,
        )
        return self._get_agent_response(response.content)

    async def stream(
        self,
        user_input: str,
        session_id: str,
    ) -> AsyncIterable[dict[str, Any]]:
        """For streaming tasks we yield the SK agent's invoke_stream progress.

        Args:
            user_input (str): User input message.
            session_id (str): Unique identifier for the session.

        Yields:
            dict: A dictionary containing the content, task completion status,
            and user input requirement.
        """
        await self._ensure_thread_exists(session_id)

        plugin_notice_seen = False
        plugin_event = asyncio.Event()

        text_notice_seen = False
        chunks: list[StreamingChatMessageContent] = []

        async def _handle_intermediate_message(
            message: 'ChatMessageContent',
        ) -> None:
            """Handle intermediate messages from the agent."""
            nonlocal plugin_notice_seen
            if not plugin_notice_seen:
                plugin_notice_seen = True
                plugin_event.set()
            # An example of handling intermediate messages during function calling
            for item in message.items or []:
                if isinstance(item, FunctionResultContent):
                    logger.info(
                        f'SK Function Result:> {item.result} for function: {item.name}'
                    )
                elif isinstance(item, FunctionCallContent):
                    logger.info(
                        f'SK Function Call:> {item.name} with arguments: {item.arguments}'
                    )
                else:
                    logger.info(f'SK Message:> {item}')

        async for chunk in self.agent.invoke_stream(
            messages=user_input,
            thread=self.thread,
            on_intermediate_message=_handle_intermediate_message,
        ):
            if plugin_event.is_set():
                yield {
                    'is_task_complete': False,
                    'require_user_input': False,
                    'content': 'Processing function calls...',
                }
                plugin_event.clear()

            if any(isinstance(i, StreamingTextContent) for i in chunk.items):
                if not text_notice_seen:
                    yield {
                        'is_task_complete': False,
                        'require_user_input': False,
                        'content': 'Building the output...',
                    }
                    text_notice_seen = True
                chunks.append(chunk.message)

        if chunks:
            yield self._get_agent_response(sum(chunks[1:], chunks[0]))

    def _get_agent_response(
        self, message: 'ChatMessageContent'
    ) -> dict[str, Any]:
        """Extracts the structured response from the agent's message content.

        Args:
            message (ChatMessageContent): The message content from the agent.

        Returns:
            dict: A dictionary containing the content, task completion status, and user input requirement.
        """
        structured_response = ResponseFormat.model_validate_json(
            message.content
        )

        default_response = {
            'is_task_complete': False,
            'require_user_input': True,
            'content': 'We are unable to process your request at the moment. Please try again.',
        }

        if isinstance(structured_response, ResponseFormat):
            response_map = {
                'input_required': {
                    'is_task_complete': False,
                    'require_user_input': True,
                },
                'error': {
                    'is_task_complete': False,
                    'require_user_input': True,
                },
                'completed': {
                    'is_task_complete': True,
                    'require_user_input': False,
                },
            }

            response = response_map.get(structured_response.status)
            if response:
                return {**response, 'content': structured_response.message}

        return default_response

    async def _ensure_thread_exists(self, session_id: str) -> None:
        """Ensure the thread exists for the given session ID.

        Args:
            session_id (str): Unique identifier for the session.
        """
        if self.thread is None or self.thread.id != session_id:
            await self.thread.delete() if self.thread else None
            self.thread = ChatHistoryAgentThread(thread_id=session_id)


# endregion
