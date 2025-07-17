import os, re
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

load_dotenv()
model = ChatOpenAI(model=os.getenv("GLOBAL_MODEL"), openai_api_key=os.getenv("OPENAI_API_KEY"))


token_regex = r"(?:ghp_[A-Za-z0-9_]{36}|github_pat_[A-Za-z0-9_]+)"
TOKEN_PATTERN = re.compile(token_regex)

def follow_ups(chat_history):
    prompt = f"""
    Your task is to draft 1-2 follow-up requests, written in the user’s voice, that guide them towards actionable insights.
    The user is looking for practical, actionable steps to take next.
    Each question should feel like the user is proactively driving the migration process forward.
    
    Chat History:
    {chat_history}
    
    IMPORTANT:
    - The follow-up requests should directly relate to the latest AI resonse.
    - Keep the requests concise nd short.
    - Always include "Proceed" type requests whenever possible.
    - Give the user the option to provide a GitHub Personal Access Token to push this business solution codebase to your GitHub account.
    - Do not ask the user to provide a GitHub Personal Access Token if it is already provided.
    
    Output Format:
    The response should be a json object as below:
    {{"follow_up_questions": [
        "Give me peformance metrics",
        "question_2",
        "question_3",
        "question_4"]
    }}
    """

    response = model.invoke(prompt)
    try:
        result = eval(response.content)
        print(result)
        questions = result.get("follow_up_questions", [])
    except:
        pass
    return questions

