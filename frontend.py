import streamlit as st
import asyncio
import os
import json
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from groq import Groq
from dotenv import load_dotenv

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

REQUIRED_ENV_VARS = ["DB_USER", "DB_PASSWORD", "DB_HOST", "GROQ_API_KEY"]
missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]

server_env = os.environ.copy()

if missing_vars:
    st.error(f"🚨 Missing Environment Variables: {', '.join(missing_vars)}")
    st.stop()

client_ai = Groq(api_key=GROQ_API_KEY)
SERVER_SCRIPT_PATH = "server.py" 

st.set_page_config(page_title="Oracle 10g Chat", layout="wide")
st.title("🤖 Oracle 10g Executor")


async def run_mcp_interaction(user_query, chat_history):
    server_params = StdioServerParameters(
        command="python", 
        args=[SERVER_SCRIPT_PATH],
        env=server_env 
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            try:
                await session.initialize()
            except Exception as e:
                return f"MCP Initialization Error: {e}. Check server logs."
                
            tools = await session.list_tools()
            
            groq_tools = []
            for tool in tools.tools:
                groq_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema
                    }
                })

            system_instruction = """
            You are an expert Oracle 10g Database Engineer Agent.
            
            YOUR WORKFLOW:
            1. ALWAYS looking for table names first if you don't know them (use `list_tables`).
            2. If you know the table, TRY to select from it.
            3. CRITICAL: If a query fails (e.g., ORA-00904 invalid identifier), DO NOT GIVE UP.
               - Immediately use `describe_table` to check the actual columns.
               - Then RETRY the query with the correct column names.
            
            STRICT RULES:
            - NO XML tags.
            - Use LEGACY Oracle Syntax (ROWNUM, no OFFSET/FETCH).
            - Answer valid user questions directly based on data.
            """

            messages = [{"role": "system", "content": system_instruction}]
            messages.extend([msg for msg in chat_history if msg["role"] != "system"][-5:])
            messages.append({"role": "user", "content": user_query})

            max_iterations = 5
            
            for i in range(max_iterations):
                try:
                    response = client_ai.chat.completions.create(
                        model="qwen/qwen3-32b", 
                        messages=messages,
                        tools=groq_tools,
                        tool_choice="auto",
                        temperature=0.3
                    )
                except Exception as e:
                    return f"Groq API Error: {e}"

                response_message = response.choices[0].message
                tool_calls = response_message.tool_calls

                if tool_calls:
                    st.toast(f"Step {i+1}: AI is thinking/running tools...", icon="🤖")
                    print(f"\n--- [Step {i+1}] AI Tool Request ---")
                    
                    messages.append(response_message)
                    for tool_call in tool_calls:
                        func_name = tool_call.function.name
                        func_args = json.loads(tool_call.function.arguments)
                        
                        print(f"Tool Call: {func_name}")
                        print(f"Arguments: {json.dumps(func_args, indent=2)}")

                        clean_args = {}
                        if func_name == "run_sql":
                             if "query" in func_args:
                                 clean_args["query"] = func_args["query"]
                             elif "sql" in func_args:
                                 clean_args["query"] = func_args["sql"]
                             else:
                                 clean_args = func_args
                        else:
                            clean_args = func_args

                        try:
                            result = await session.call_tool(func_name, arguments=clean_args)
                            tool_output = result.content[0].text
                        except Exception as e:
                            tool_output = f"Tool Execution Error: {str(e)}"

                        print(f"Tool Output: {tool_output[:500]}..." if len(tool_output) > 500 else f"Tool Output: {tool_output}")

                        messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": func_name,
                            "content": tool_output
                        })
                    
                
                else:
                    final_ans = response_message.content
                    print(f"\n--- [Final Answer] ---\n{final_ans}\n")
                    return final_ans
            
            return "⚠️ Max iterations reached. The AI tried to solve it but got stuck in a loop."

# --- UI ---
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    if message["role"] != "system":
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

if prompt := st.chat_input("Enter natural language SQL command (e.g., show customers table)"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Processing..."):
            try:
                resp = asyncio.run(run_mcp_interaction(prompt, st.session_state.messages))
                st.markdown(resp)
                st.session_state.messages.append({"role": "assistant", "content": resp})
            except Exception as e:
                st.error(f"System Error: {e}")