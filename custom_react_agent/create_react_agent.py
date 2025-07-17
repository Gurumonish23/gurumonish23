"""
React Agent Framework - A configurable framework for creating React agents with LangGraph
"""

import json
import os
from typing import (
    Annotated,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    TypedDict,
    Union,
)
import time
import langchain_core
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt.tool_node import ToolNode
from langgraph.graph.message import add_messages
from langchain_google_vertexai import ChatVertexAI, VertexAI
from langgraph.types import interrupt, Command


class AgentState(TypedDict):
    """The state of the agent."""
    # add_messages is a reducer
    # See https://langchain-ai.github.io/langgraph/concepts/low_level/#reducers
    messages: Annotated[Sequence[BaseMessage], add_messages]


class ReactAgentConfig:
    """Configuration class for the React Agent framework."""
    
    def __init__(
        self,
        model: Optional[Any] = None,
        tools: List[BaseTool] = None,
        system_prompt: str = "You are a helpful AI assistant, please respond to the users query to the best of your ability!",
        chat_model_for_decisions: Optional[Any] = None,
        decision_prompt: Optional[str] = None,
        planning_prompt: Optional[str] = None,
        create_agent_node: Optional[Callable] = None,
        create_tools_node: Optional[Callable] = None,
        create_decision_node: Optional[Callable] = None,
        create_planning_node: Optional[Callable] = None,
        start_with_planning: bool = True
    ):
        """
        Initialize the React Agent configuration.
        
        Args:
            model: The language model to use (defaults to gpt-4o)
            tools: List of tools the agent can use
            system_prompt: The prompt to use for the agent
            chat_model_for_decisions: Model for decision making (defaults to same as main model)
            decision_prompt: Custom prompt for the decision node
            planning_prompt: Custom prompt for the planning node
            create_agent_node: Custom function to create the agent node
            create_tools_node: Custom function to create the tools node
            create_decision_node: Custom function to create the decision node
            create_planning_node: Custom function to create the planning node
            start_with_planning: Whether to start the flow with planning or agent node
        """
        # Set default model if none provided
        if model is None:
            self.model = ChatOpenAI(model="gpt-4o")
        else:
            self.model = model
            
        # Set default tools if none provided
        self.tools = tools or []
        
        # Set system prompt
        self.system_prompt = system_prompt
        
        # Set the chat model for decision making
        self.chat_model_for_decisions = chat_model_for_decisions or self.model
        
        # Set default decision prompt if none provided
        if decision_prompt is None:
            self.decision_prompt = """Based on the **user's ask** and model's actions, decide whether the workflow should continue or not.
            Respond with just 'continue' or 'end'.
            
            Chat History:
            {messages}
            """
        else:
            self.decision_prompt = decision_prompt
        # Set default planning prompt if none provided
        if planning_prompt is None:
            self.planning_prompt = """
            Chat History:
            {messages}
            
            Instructions:
            - You are the brain of the ReAct agent. Your job is to give the reasoning, thinking, and plan of action to the agent.
            - Based on the **user's ask** and model's actions, decide what the next action should be.
            - If the actions plans are complete, instruct the model to summarize the results as an answer to the user's original query.
            
            Available tools:
            {tools_info}
            
            Example Workflow:
            User: What is the weather in New York?
            You: I need to search for the weather in New York. I'll use the Search tool to do this.
            Model: Calling weather tool...
            
            Output should be in the following format:
            Thought: [Your reasoning here]
            Observation: [Result of the action] (if any)
            """
        else:
            self.planning_prompt = planning_prompt
            
        # Set custom node functions if provided
        self.create_agent_node = create_agent_node
        self.create_tools_node = create_tools_node
        self.create_decision_node = create_decision_node
        self.create_planning_node = create_planning_node
        
        # Whether to start with planning or agent
        self.start_with_planning = start_with_planning
        
        # Bind tools to the model if there are any
        if self.tools:
            self.tools_by_name = {tool.name: tool for tool in self.tools}
            self.model = self.model.bind_tools(self.tools)


class ReactAgentBuilder:
    """Builder class for creating React agents."""
    
    def __init__(self, config: ReactAgentConfig):
        """Initialize the builder with a configuration."""
        self.config = config
    
    def build_agent_node(self):
        """Build the agent node that calls the model."""
        if self.config.create_agent_node:
            return self.config.create_agent_node(self.config)
        
        def call_model(state: AgentState, config: RunnableConfig):
            system_prompt = SystemMessage(self.config.system_prompt)
            try:
                response = self.config.model.invoke([system_prompt] + state["messages"], config)
            except Exception as e:
                print("Retrying model call after 40 seconds due to error -\n:", e)
                time.sleep(40)
                response = self.config.model.invoke([system_prompt] + state["messages"], config)
            # try:
            #     response = AIMessage(content=response.content, additional_kwargs=response.additional_kwargs)
            # except Exception as e:
            #     pass
            return {"messages": [response]}
        
        return call_model
    
    def build_planning_node(self):
        """Build the planning node that creates a plan of action."""
        if self.config.create_planning_node:
            return self.config.create_planning_node(self.config)
        
        def planning_node(state: AgentState):
            messages = state["messages"]
            tools_info = '\n'.join(f'-Name: {tool.name} - Description: {tool.description} - (args: {tool.args})' 
                                 for tool in self.config.tools)
            
            prompt = self.config.planning_prompt.format(
                messages=messages[-50:],
                tools_info=tools_info
            )
            try:
                try:
                    response = self.config.chat_model_for_decisions.invoke(prompt).content
                except Exception as e:
                    response = self.config.chat_model_for_decisions.invoke(prompt)
            except Exception as e:
                print("Retrying planning node after 40 seconds due to error -\n:", e)
                time.sleep(40)
                try:
                    response = self.config.chat_model_for_decisions.invoke(prompt).content
                except Exception as e:
                    response = self.config.chat_model_for_decisions.invoke(prompt)
            print("planning response================================================\n\n")
            print(response)
            print("\n\nplanning response================================================")
            response = AIMessage(content=response.strip())
            return {"messages": [response]}
        
        return planning_node
    
    def build_decision_node(self):
        """Build the decision node that determines flow control."""
        if self.config.create_decision_node:
            return self.config.create_decision_node(self.config)
        
        def decision_node(state: AgentState):
            print("************************************************")
            print("Decision Node")
            
            def should_continue(messages):
                prompt = self.config.decision_prompt.format(messages=messages)
                try:
                    try:
                        response = self.config.chat_model_for_decisions.invoke(prompt).content
                    except Exception as e:
                        response = self.config.chat_model_for_decisions.invoke(prompt)
                except Exception as e:
                    print("Retrying decision node after 40 seconds due to error -\n:", e)
                    time.sleep(40)
                    try:
                        response = self.config.chat_model_for_decisions.invoke(prompt).content
                    except Exception as e:
                        response = self.config.chat_model_for_decisions.invoke(prompt)
                print("================================================")
                print(response)
                print("================================================")
                if "continue" in response.lower().strip():
                    return "continue"
                else:
                    return "end"
            
            messages = state["messages"]
            last_message = messages[-1]
            # If there is a tool call, then we route to tools
            if last_message.tool_calls:
                return "tools"
            # Otherwise, check if we should continue or end
            else:
                # if should_continue(messages[-10:]) == "end":
                #     return "rejected"
                # return "approved"
                return "rejected"
        
        return decision_node
    
    def build_graph(self):
        """Build the graph with all nodes and edges."""
        # Get the nodes
        agent_node = self.build_agent_node()
        tools_node = ToolNode(tools=self.config.tools)
        decision_node = self.build_decision_node()
        planning_node = self.build_planning_node()
        
        # Create the graph
        workflow = StateGraph(AgentState)
        
        # Add the nodes
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", tools_node)
        workflow.add_node("planning", planning_node)
        
        # Set the entry point
        if self.config.start_with_planning:
            workflow.set_entry_point("planning")
        else:
            workflow.set_entry_point("agent")
        
        workflow.add_edge("planning", "agent")  # Add edge from planning to agent
        
        # Add conditional edge from agent to decision
        workflow.add_conditional_edges(
            source="agent",
            path=decision_node,
            path_map={
                "tools": "tools",         # If tool call detected, go to tools
                "approved": "planning",   # If approved, go back to planning
                "rejected": END,          # If rejected, end the workflow
            },
        )
        
        # Add edge from tools back to planning
        workflow.add_edge("tools", "planning")
        
        # Compile the graph
        return workflow.compile()


def create_react_agent(
    model=None,
    tools=None,
    system_prompt=None,
    chat_model_for_decisions=None,
    decision_prompt=None,
    planning_prompt=None,
    create_agent_node=None,
    create_tools_node=None,
    create_decision_node=None,
    create_planning_node=None,
    start_with_planning=True,
):
    """
    Create a React agent with the given configuration.
    
    Args:
        model: The language model to use
        tools: List of tools the agent can use
        system_prompt: The prompt to use for the agent
        chat_model_for_decisions: Model for decision making
        decision_prompt: Custom prompt for the decision node
        planning_prompt: Custom prompt for the planning node
        create_agent_node: Custom function to create the agent node
        create_tools_node: Custom function to create the tools node
        create_decision_node: Custom function to create the decision node
        create_planning_node: Custom function to create the planning node
        start_with_planning: Whether to start with planning (True) or agent (False)
    
    Returns:
        The compiled graph for the React agent
    """
    
    default_system_prompt = """
    You are a friendly and helpful AI assistant designed to execute tasks and fulfill user requests step by step.

    - Use tools as needed to complete each step of the plan.
    - Only call **one tool at a time** — never make multiple tool calls in a single step.
    - If something is unclear, ask the user for clarification before proceeding.
    - Keep your tone conversational, approachable, and professional.
    
    Once all steps are completed, provide a summary of the results that directly answers the user’s original request.
    """
    
    config = ReactAgentConfig(
        model=model,
        tools=tools,
        system_prompt=system_prompt or default_system_prompt,
        chat_model_for_decisions=chat_model_for_decisions,
        decision_prompt=decision_prompt,
        planning_prompt=planning_prompt,
        create_agent_node=create_agent_node,
        create_tools_node=create_tools_node,
        create_decision_node=create_decision_node,
        create_planning_node=create_planning_node,
        start_with_planning=start_with_planning,
    )
    
    builder = ReactAgentBuilder(config)
    return builder.build_graph()