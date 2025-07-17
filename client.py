import os
import sys
import json
import asyncio
import traceback
import threading
import time
from typing import List
from pathlib import Path as FilePath
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_mcp_adapters.client import MultiServerMCPClient
#from langgraph.prebuilt import create_react_agent
from custom_react_agent.create_react_agent import create_react_agent
from prompts.systemPrompts import *
from utils.files import save_upload_file_tmp
from app import config_router
from utils.followups import follow_ups

load_dotenv()

BASE_DIR = FilePath(__file__).resolve().parent
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(config_router)

app.mount("/static", StaticFiles(directory="static"), name="static")

model = ChatOpenAI(model=os.getenv("GLOBAL_MODEL"), openai_api_key=os.getenv("OPENAI_API_KEY"))
decision_model = ChatOpenAI(model=os.getenv("GLOBAL_MODEL"), openai_api_key=os.getenv("OPENAI_API_KEY"))

chat_history=[]

def load_prompt(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"Prompt file missing: {path}"

PROMPT_FILES = {
    "business_workflow_orchestration": "prompts/business_workflow_orchestration_prompt.md",
    "knowledge_base": "prompts/knowledge_base_prompt_template.md",
    "final_business_usecase": "MCP_servers/final_business_usecase.txt",
    "playground_prompt": "prompts/playground_orchestration_prompt_template.md"
}

PROMPT_MESSAGES = [
    SystemMessage(content=load_prompt(PROMPT_FILES["business_workflow_orchestration"])),
]


# Build platform-independent paths
# ── MCP Server Configuration (Static) ────────────────────────────────────────────


uploaded_files = {}

def monitor_uploaded_files():
    while True:
        try:
            for filename in os.listdir(UPLOAD_DIR):
                if filename.endswith((".pdf", ".docx")):
                    uploaded_files[filename] = os.path.join(UPLOAD_DIR, filename)
        except Exception as e:
            print(f"[Monitor Error] {e}")
        time.sleep(5)

threading.Thread(target=monitor_uploaded_files, daemon=True).start()

class ToolCallbackHandler(BaseCallbackHandler):
    def __init__(self, ws: WebSocket):
        self.ws = ws

    async def on_tool_start(self, tool, input_str, **kwargs):
        tool_name = tool.get("name", str(tool)) if isinstance(tool, dict) else getattr(tool, "name", str(tool))
        await self.ws.send_json({"type": "intermediate_step", "content": f"Calling tool: {tool_name}\n📥 Input: {input_str}"})

    async def on_tool_end(self, output, **kwargs):
        try:
            content = output.content if isinstance(output, ToolMessage) else str(output)
            try:
                parsed = json.loads(content)
                formatted = json.dumps(parsed, indent=2)
                await self.ws.send_json({"type": "intermediate_step", "content": f"Tool Output:\n{formatted}"})
            except:
                await self.ws.send_json({"type": "intermediate_step", "content": f"Tool Output:\n{content}"})
        except Exception as e:
            await self.ws.send_json({"type": "error", "message": f"Callback error: {str(e)}"})

@app.websocket("/ws/chat")
async def sdlc_ws(websocket: WebSocket):
    await websocket.accept()
    chat_history.extend(PROMPT_MESSAGES.copy())
    mcp_server_configs = {
    "custom_mcp": {
        "command": "python",
        "args": ["MCP_servers/custom_mcp.py"],
        "transport": "stdio"
    }
    
}

    try:
        print(mcp_server_configs)
        async with MultiServerMCPClient(mcp_server_configs) as client:
            print("tools")
            tools = client.get_tools()
            
            #agent = create_react_agent(model=model, tools=tools)
            agent = create_react_agent(model=model, tools=tools, chat_model_for_decisions=decision_model,
                                       system_prompt=SYSTEM_PROMPT, planning_prompt=PLANNING_PROMPT, decision_prompt=DECISION_PROMPT)
            tools_desc = [
                {'name': tool.name, 'description': tool.description} for tool in tools]
            
            await websocket.send_json({
                "type": "intermediate_step",
                "content": f"Tools loaded: {tools_desc}"
            })
            while True:
                data = await websocket.receive_json()
                user_input = data.get("content", "").strip()

                if not user_input:
                    await websocket.send_json({"type": "error", "message": "Empty message."})
                    continue

                file_list_msg = "\n".join(f"- {fname}" for fname in uploaded_files.keys())
                chat_history.append(SystemMessage(content=f"Current uploaded files:\n{file_list_msg}"))
                chat_history.append(HumanMessage(content=user_input))
                config = RunnableConfig(callbacks=[ToolCallbackHandler(websocket)], recursion_limit=100)

                async for step in agent.astream({"messages": chat_history}, config=config):
                    print(f"Received step: {step}")
                    # e.g., "planner", "agent", etc.
                    step_key = next(iter(step))
                    step_data = step[step_key]
                    messages = step_data.get("messages", [])

                    for msg in messages:
                        if isinstance(msg, AIMessage):
                            if step_key == "planning":
                                await websocket.send_json({
                                    "type": "intermediate_step",
                                    "content": msg.content
                                })
                            elif step_key == "agent":
                                if hasattr(msg, "tool_calls") and msg.tool_calls:
                                    print("calling tool")
                                    pass
                                elif isinstance(msg.content, list):
                                    if len(msg.content) > 0:
                                        await websocket.send_json({
                                            "type": "ai_response",
                                            "content": " ".join(msg.content)
                                        })
                                    continue
                                elif msg.content.strip() != "":
                                    await websocket.send_json({
                                        "type": "ai_response",
                                        "content": msg.content
                                    })
                                chat_history.append(msg)
                                # follow_ups_response = follow_ups(
                                #     chat_history)
                                # print(
                                #     f"Follow-up questions: {follow_ups_response}")
                                # await websocket.send_json({
                                #     "type": "followup_questions",
                                #     "content": follow_ups_response["follow_up_questions"]
                                # })
                        if isinstance(msg, ToolMessage):
                            msg.content = msg.content.strip()
                            chat_history.append(msg)

                 
    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception as e:
        print("Error:", traceback.format_exc())
        await websocket.send_json({"type": "error", "message": str(e)})


@app.websocket("/ws/playground")
async def playground(websocket: WebSocket):
    await websocket.accept()
    global chat_history
    final_business_usecase = load_prompt(PROMPT_FILES["final_business_usecase"])
    playground_orchestration = load_prompt(PROMPT_FILES["playground_prompt"]).format(business_usecase = final_business_usecase)

    chat_history.append("business usecase"+ final_business_usecase)
    chat_history.append(
       SystemMessage(content= playground_orchestration)
    )
    chat_history.append(SystemMessage(content=load_prompt(PROMPT_FILES["knowledge_base"])))
    print(chat_history)
    
    playground_configs = {
        "filesystem": {
            "command": "npx",
            "args": [
                "-y",
                "@modelcontextprotocol/server-filesystem",
                str(BASE_DIR),
            ],
            "transport": "stdio"
        },
        "fetch": {
            "command": "python",
            "args": ["-m", "mcp_server_fetch"],
            "transport": "stdio"
        },
        "searxng": {
            "command": "npx",
            "args": ["-y", "@cablate/mcp-doc-forge"],
            "transport": "stdio",
        },
        "youtube-transcript": {
            "command": "npx",
            "args": ["-y", "@sinco-lab/mcp-youtube-transcript"],
            "transport": "stdio",
        },
        "chroma": {
        "command": "uvx",
        "args": [
            "chroma-mcp"
        ]
    }
    }
    try:
        async with MultiServerMCPClient(playground_configs) as client:
            print("tools")
            tools = client.get_tools()
            print(tools)
            #agent = create_react_agent(model=model, tools=tools)
            agent = create_react_agent(model=model, tools=tools, chat_model_for_decisions=decision_model,
                                       system_prompt=SYSTEM_PROMPT, planning_prompt=PLANNING_PROMPT, 
                                       decision_prompt=DECISION_PROMPT
                                       )
            tools_desc = [
                {'name': tool.name, 'description': tool.description} for tool in tools
                ]
            
            await websocket.send_json({
                "type": "intermediate_step",
                "content": f"Tools loaded: {tools_desc}"
            })
            while True:
                data = await websocket.receive_json()
                user_input = data.get("content", "").strip()

                if not user_input:
                    await websocket.send_json({"type": "error", "message": "Empty message."})
                    continue

                file_list_msg = "\n".join(f"- {fname}" for fname in uploaded_files.keys())
                chat_history.append(SystemMessage(content=f"Current uploaded files:\n{file_list_msg}"))
                chat_history.append(HumanMessage(content=user_input))
                config = RunnableConfig(callbacks=[ToolCallbackHandler(websocket)], recursion_limit=100)

                async for step in agent.astream({"messages": chat_history}, config=config):
                    print(f"Received step: {step}")
                    # e.g., "planner", "agent", etc.
                    step_key = next(iter(step))
                    step_data = step[step_key]
                    messages = step_data.get("messages", [])

                    for msg in messages:
                        if isinstance(msg, AIMessage):
                            if step_key == "planning":
                                await websocket.send_json({
                                    "type": "intermediate_step",
                                    "content": msg.content
                                })
                            elif step_key == "agent":
                                if hasattr(msg, "tool_calls") and msg.tool_calls:
                                    print("calling tool")
                                    pass
                                elif isinstance(msg.content, list):
                                    if len(msg.content) > 0:
                                        await websocket.send_json({
                                            "type": "ai_response",
                                            "content": " ".join(msg.content)
                                        })
                                    continue
                                elif msg.content.strip() != "":
                                    await websocket.send_json({
                                        "type": "ai_response",
                                        "content": msg.content
                                    })
                                chat_history.append(msg)
                                follow_ups_response = follow_ups(
                                    chat_history)
                                print(
                                    f"Follow-up questions: {follow_ups_response}")
                                await websocket.send_json({
                                    "type": "followup_questions",
                                    "content": follow_ups_response
                                })
                        if isinstance(msg, ToolMessage):
                            msg.content = msg.content[:20000]
                            chat_history.append(msg)

                 
    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception as e:
        print("Error:", traceback.format_exc())
        await websocket.send_json({"type": "error", "message": str(e)})

@app.get("/")
async def root():
    return {"status": "OK"}

@app.post("/upload")
async def upload_doc(files: List[UploadFile] = File(...)):
    uploaded = []
    for file in files:
        if not file.filename.endswith((".pdf", ".docx", ".csv", ".xlsx", ".txt")):
            continue
        filepath = save_upload_file_tmp(file)
        uploaded_files[file.filename] = filepath
        uploaded.append(filepath)
    return {"message": "Files uploaded successfully", "uploaded_files": uploaded}
    
@app.get("/ws/chat")
async def serve_ui():
    return FileResponse("static/chat_ui.html")

@app.get("/ws/playground")
async def serve_ui():
    return FileResponse("static/chat_playground.html")
