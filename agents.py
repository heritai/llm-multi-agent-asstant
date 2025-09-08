from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.types import Command, interrupt
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.tools.retriever import create_retriever_tool
from langchain_core.tools import tool
from langchain_community.llms import Ollama
from langchain_ollama import ChatOllama
from langgraph.prebuilt import ToolNode, tools_condition
from utils import load_vectorstore

# --- System Prompts ---
dialogue_agent_system_prompt = """
You are a dialogue agent specialized in GDPR and AI ACT. Your goal is to extract the following information from user input:
- Company's name : string
- Sector or industry: string
- Country : string
- Size of company (number of employees or scale) : integer
- The categories of data being collected/processed : list of strings

If information is missing, gently ask the user to provide it. Update extracted values after each user response and continue until all information is extracted.
When all required information is extracted, say "**All information have been extracted!**" and do not say anything after.
"""

gdpr_analyser_system_prompt = """
You are a GDPR expert. Analyze input information about companies and provide brief recommendations to ensure GDPR compliance. Add GDPR reference for each recommendation in parentheses.
Use your general knowledge and retrieved documents at tool calling. Do not say anything after your analysis.
"""

act_analyser_system_prompt = """
You are an AI ACT expert. Analyze input information about companies and their AI policies, and provide brief risk analysis based on AI Act. Add AI Act reference for each recommendation in parentheses.
Use your general knowledge and retrieved documents at tool calling. Do not say anything after your analysis.
"""

summarizer_system_prompt = """
You are a legal expert specialized in GDPR and AI Act. Summarize the GDPR and AI Act analysis, making a brief and clear summary of obligations, risks, and recommendations.
Do not say anything after the summary.
"""

# --- Pydantic Model ---
class ComplianceInfo(BaseModel):
    company_name: Optional[str] = Field(default=None, description="The company's name in the input information")
    country: str = Field(description="The country in the input information")
    industry: str = Field(description="The sector or industry in the input information")
    company_size: int = Field(description="The size of company/number of employees in the input information")
    data_types_collected: Optional[List[str]] = Field(default=None, description="The category or categories of data being collected/processed in the input information")

parser = PydanticOutputParser(pydantic_object=ComplianceInfo)

# --- LLM Setup ---
llm = ChatOllama(model="llama3.2:1b", temperature=0)
llm_with_tools = llm.bind_tools([ComplianceInfo])

# --- Agent Definitions ---
def dialogue_agent(state: MessagesState):
    """Dialogue agent for extracting company compliance info."""
    user_input = state["messages"]
    llm_response = llm.invoke([SystemMessage(dialogue_agent_system_prompt)] + user_input)
    return {"messages": [llm_response]}

def human(state: MessagesState) -> Command[Literal["dialogue"]]:
    """Node for collecting user input."""
    user_input = interrupt(value="Ready for user input.")
    return Command(
        update={
            "messages": [{
                "role": "human",
                "content": user_input,
            }]
        },
        goto="dialogue"
    )

def json_extractor(state: MessagesState):
    """Extract structured compliance info from user input."""
    user_input = state["messages"][-1].content
    llm_response = llm_with_tools.invoke([HumanMessage(content=user_input)])
    return {"messages": [llm_response]}

def router(state: MessagesState):
    """Route between asking human and extracting info."""
    last_message = state["messages"][-1].content
    if 'All information have been extracted!' in last_message:
        return 'extractor'
    return 'ask_human'

# --- GDPR Tools ---
gdpr_vectorstore = load_vectorstore('gdpr')
gdpr_retriever = gdpr_vectorstore.as_retriever()
gdpr_retriever_tool = create_retriever_tool(
    gdpr_retriever,
    "GDPR retriever",
    "Retrieves related articles from GDPR",
)
gdpr_tool_node = ToolNode([gdpr_retriever_tool])
llm_gdpr_tool = llm.bind_tools([gdpr_retriever_tool])

def gdpr_analyser(state: MessagesState):
    """Analyze GDPR compliance."""
    ai_input = state["messages"]
    llm_response = llm_gdpr_tool.invoke([SystemMessage(gdpr_analyser_system_prompt)] + ai_input)
    return {"messages": [llm_response]}

# --- AI Act Tools ---
act_vectorstore = load_vectorstore('act')
act_retriever = act_vectorstore.as_retriever()
act_retriever_tool = create_retriever_tool(
    act_retriever,
    "AI Act retriever",
    "Retrieves related articles from AI Act",
)
act_tool_node = ToolNode([act_retriever_tool])
llm_act_tool = llm.bind_tools([act_retriever_tool])

def act_analyser(state: MessagesState):
    """Analyze AI Act compliance."""
    ai_input = state["messages"]
    llm_response = llm_act_tool.invoke([SystemMessage(act_analyser_system_prompt)] + ai_input)
    return {"messages": [llm_response]}

def summarizer(state: MessagesState):
    """Summarize GDPR and AI Act analysis."""
    ai_input1 = state["messages"][-1].content
    ai_input2 = state["messages"][-2].content
    summary_input = f"This is the first analysis:\n{ai_input1}\nThis is the second analysis:\n{ai_input2}"
    llm_response = llm.invoke([SystemMessage(summarizer_system_prompt)] + [HumanMessage(content=summary_input)])
    return {"messages": [llm_response]}

# --- LangGraph Flow Setup ---
memory = MemorySaver()
graph = StateGraph(MessagesState)
graph.add_node("dialogue", dialogue_agent)
graph.add_node("ask_human", human)
graph.add_node("extractor", json_extractor)
graph.add_node("gdpr_analyser", gdpr_analyser)
graph.add_node("gdpr_retriever", gdpr_tool_node)
graph.add_node("ai_act_analyser", act_analyser)
graph.add_node("ai_act_retriever", act_tool_node)
graph.add_node("summary", summarizer)

graph.add_edge(START, "dialogue")
graph.add_edge("ask_human", "dialogue")
graph.add_conditional_edges("dialogue", router, path_map=["ask_human", "extractor"])
graph.add_edge("extractor", "gdpr_analyser")
graph.add_edge("extractor", "ai_act_analyser")
graph.add_conditional_edges("gdpr_analyser", tools_condition, {"tools": "gdpr_retriever", "__end__": "summary"})
graph.add_edge("gdpr_retriever", "gdpr_analyser")
graph.add_conditional_edges("ai_act_analyser", tools_condition, {"tools": "ai_act_retriever", "__end__": "summary"})
graph.add_edge("ai_act_retriever", "ai_act_analyser")

graph_out = graph.compile(checkpointer=memory)
config = {"configurable": {"thread_id": "123"}}

#def stream_graph_updates(user_input: str):
#    """Stream updates from the graph for each user input."""
#    for event in graph_out.stream({"messages": [{"role": "user", "content": user_input}]}, config, stream_mode="updates"):
#        for value in event.values():
#            print("Assistant:", value)

#if __name__ == "__main__":
#    while True:
#        user_input = input("User: ")
#        if user_input.lower() in ["quit", "exit", "q"]:
#            print("Goodbye!")
#            break
#        stream_graph_updates(user_input)