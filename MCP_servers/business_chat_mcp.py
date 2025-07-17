from openai import OpenAI
import os
import sys
import pandas as pd
import sys, io, ast
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field, HttpUrl
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from mcp.server.fastmcp import FastMCP
from prompts.business_usecase_prompt import (business_usecase_enrich_prompt, verification_business_usecase_prompt,
                                             final_version_business_usecase_prompt)
from prompts.finetuning_prompt import config_prompt

load_dotenv()

global_llm = ChatOpenAI(
    model_name = os.getenv("GLOBAL_MODEL"),
    openai_api_key=os.getenv("OPENAI_API_KEY")
)


anthropic_llm = ChatAnthropic(
    model="claude-3-5-sonnet-20240620",
    anthropic_api_key=os.getenv("ANTHROPIC_API_KEY")
)

finetuning_llm = ChatOpenAI(
            model_name= os.getenv("LIGA_METRICS_MODEL"),
            openai_api_key=os.getenv("OPENAI_API_KEY")
        )

mcp = FastMCP("fine_tuning_MCP")

FINAL_USECASE_PATH = Path("final_business_usecase.txt")
@mcp.tool("business_enrich", description="business enriched usecase by openAI model")
def business_enrich_tool(business_usecase: str):
    try:
        ai_msg = global_llm.invoke(business_usecase_enrich_prompt.format(user_statement=business_usecase))
        return ai_msg.content
    except Exception as e:
        print(f"Generation error: {e}")

@mcp.tool("verification", description="return yaml comments for verification of openAI enriched businessusecase by anthropic model")
def verification_business_enrich_tool(enriched_business_usecase: str):
    try:
       ai_msg = anthropic_llm.invoke(verification_business_usecase_prompt.format(enriched_business_usecase=enriched_business_usecase))
       return ai_msg.content 
       
    except Exception as e:
        print(f"Generation error: {e}")

@mcp.tool("final_version_business_usecase", description="final version of business usecase")
def verification_business_enrich_tool(enriched_business_usecase, review_comments):
    try:
       ai_msg = global_llm.invoke(final_version_business_usecase_prompt.format(enriched_business_usecase=enriched_business_usecase,
                                                                       review_comments=review_comments))
       
       content = ai_msg.content
       # write (overwrite) to the file
       FINAL_USECASE_PATH.write_text("Final version of business usecase:" + content, encoding="utf-8")
       return content 
       
    except Exception as e:
        print(f"Generation error: {e}")

# @mcp.tool("finetuning_model", description="Generate the POC solution and enterprise stack from the enriched final version of business usecase")
# def finetuning_model_tool(enriched_usecase: str):
#     try:
#        ai_msg = finetuning_llm.invoke(config_prompt.format(enriched_usecase=enriched_usecase))
#        return ai_msg.content 
       
#     except Exception as e:
#         print(f"Generation error: {e}")

@mcp.tool("finetuning_model", description="Generate the simple solution from the enriched final version of business usecase")
def configuration_tool(enriched_usecase: str):
    try:
       ai_msg = global_llm.invoke(config_prompt.format(enriched_usecase=enriched_usecase))
       return ai_msg.content 
    except Exception as e:
        print(f"Generation error: {e}")

if __name__ == "__main__":
    import sys
    print("starting fine_tuning_MCP....", file=sys.stderr)
    mcp.run(transport="stdio")
