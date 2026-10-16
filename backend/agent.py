import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from backend.tools import ALL_TOOLS

load_dotenv()

def get_agent_executor():
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("MODEL")
    base_url = os.getenv("BASEURL")

    if not api_key or "your_actual" in api_key:
        raise ValueError("Valid OPENAI_API_KEY was not found in environment or .env file.")

    # Initialize OpenAI Chat Model
    llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key)
    
    # Compile ReAct Graph agent with custom tools
    return create_react_agent(llm, tools=ALL_TOOLS)

async def run_agent_stream(user_prompt: str, log_callback, response_callback):
    """
    Executes the LangGraph workflow and streams intermediate steps and tool 
    outputs directly back to the Flet frontend UI callbacks.
    """
    try:
        agent = get_agent_executor()
        await log_callback(f"Prompt received: '{user_prompt}'", "INFO")
        await log_callback("Analyzing task & planning tool calls...", "TOOL")

        inputs = {"messages": [HumanMessage(content=user_prompt)]}

        # Asynchronously stream execution state chunks
        async for chunk in agent.astream(inputs, stream_mode="updates"):
            for node_name, state_update in chunk.items():
                messages = state_update.get("messages", [])
                for msg in messages:
                    if isinstance(msg, AIMessage):
                        if msg.tool_calls:
                            for call in msg.tool_calls:
                                await log_callback(
                                    f"Invoking Tool: {call['name']}({call['args']})", 
                                    "TOOL"
                                )
                        elif msg.content:
                            await response_callback(msg.content)

                    elif isinstance(msg, ToolMessage):
                        await log_callback(
                            f"Tool Output [{msg.name}]: {msg.content}", 
                            "SUCCESS"
                        )

        await log_callback("Task execution completed.", "SUCCESS")

    except Exception as e:
        await log_callback(f"Execution Error: {str(e)}", "ERROR")
        await response_callback(f"Agent encountered an error: {str(e)}")