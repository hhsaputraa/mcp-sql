import streamlit as st
import asyncio
import os
import json
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from groq import Groq
from datetime import datetime
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
st.title("🤖 Oracle 10g")


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

            # --- SYSTEM PROMPT ---
            current_date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            system_instruction = f"""
            You are an expert Oracle 10g Database Engineer Agent.
            Current Date/Time: {current_date_str}
            
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
            
            FORMATTING PROTOCOL:
            1. If data is a LIST of records (2+ rows) -> YOU MUST GENERATE A MARKDOWN TABLE.
            2. If data is a SINGLE value (e.g. Count) -> Present as bold text.
            3. If data is a SINGLE row -> List as Key-Value points.
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

# --- UI & STYLING ---
st.markdown("""
    <style>
    /* Global Styling */
    .main {
        background-color: #f0f2f5; /* Light gray background like WhatsApp Web */
        padding-top: 2rem;
    }
    
    /* Hide Streamlit Default Elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Chat Bubble Styling */
    .chat-container {
        display: flex;
        flex-direction: column;
        gap: 10px;
        padding-bottom: 100px;
    }
    
    .chat-bubble {
        padding: 10px 15px;
        border-radius: 10px;
        margin-bottom: 10px;
        max-width: 70%;
        line-height: 1.5;
        font-family: sans-serif;
        position: relative;
        word-wrap: break-word;
    }
    
    .user-bubble {
        background-color: #dcf8c6; /* WhatsApp Green */
        color: #000;
        align-self: flex-end;
        border-top-right-radius: 0;
        margin-left: auto;
        box-shadow: 0 1px 2px rgba(0,0,0,0.1);
    }
    
    .ai-bubble {
        background-color: #ffffff; /* White */
        color: #000;
        align-self: flex-start;
        border-top-left-radius: 0;
        margin-right: auto;
        box-shadow: 0 1px 2px rgba(0,0,0,0.1);
    }
    
    .timestamp {
        font-size: 0.7em;
        color: #999;
        margin-top: 5px;
        text-align: right;
    }
    
    /* Code block override inside bubbles */
    .stCodeBlock {
        background-color: #f8f8f8 !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/5/50/Oracle_logo.svg", width=150)
    st.markdown("### 🤖 Oracle 10g")
    st.markdown("---")
    
    st.success("🟢 System Online")
    st.info(f"📅 Date: {datetime.now().strftime('%Y-%m-%d')}")
    
    st.markdown("---")
    if st.button("🗑️ Clear Chat History", type="primary"):
        st.session_state.messages = []
        st.rerun()

    st.markdown("---")
    st.caption("v1.2.0 | Agentic Mode Active")

# --- MAIN CHAT INTERFACE ---
if "messages" not in st.session_state:
    st.session_state.messages = []

# Container for chat messages
chat_container = st.container()

with chat_container:
    # Use HTML to render bubbles
    for message in st.session_state.messages:
        role = message["role"]
        content = message["content"]
        
        if role == "user":
            st.markdown(f'''
                <div class="chat-bubble user-bubble">
                    {content}
                </div>
            ''', unsafe_allow_html=True)
        elif role == "assistant":
            # For assistant, we might want to render markdown properly
            # Adding a wrapper div styling it as a bubble
             with st.chat_message("assistant", avatar="🤖"):
                st.markdown(content)
        elif role == "tool":
            with st.status(f"🛠️ Tool Output: {message['name']}", expanded=False):
                st.code(content)

# Input Area
if prompt := st.chat_input("Ketik perintah SQL natural (cth: lihat tabel nasabah)"):
    # Add User Message to State
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # Render User Message Immediately
    with chat_container:
        st.markdown(f'''
            <div class="chat-bubble user-bubble">
                {prompt}
            </div>
        ''', unsafe_allow_html=True)

    # Process AI Response
    with st.spinner("🤖 AI sedang berpikir..."):
        try:
            resp = asyncio.run(run_mcp_interaction(prompt, st.session_state.messages))
            
            # Add AI Message to State
            st.session_state.messages.append({"role": "assistant", "content": resp})
            
            # Rerun to update the view properly
            st.rerun()
            
        except Exception as e:
            st.error(f"System Error: {e}")