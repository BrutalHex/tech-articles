from typing import Any

from langchain_chroma import Chroma
from langchain_core.tools import StructuredTool

COLLECTIONS = {
    "research_search": "research_docs",
    "finance_search": "finance_docs",
    "legal_search": "legal_docs",
}


def get_vectorstore(
    collection_name: str,
    embedding_function: Any,
    host: str,
    port: int,
):
    """Connect to the Chroma server."""
    return Chroma(
        collection_name=collection_name,
        embedding_function=embedding_function,
        host=host,
        port=port,
    )


def get_retriever(
    collection_name: str,
    embedding_function: Any,
    host: str,
    port: int,
):
    vectorstore = get_vectorstore(collection_name, embedding_function, host, port)
    return vectorstore.as_retriever(search_kwargs={"k": 5})


def make_collection_search_tool(
    tool_name: str,
    collection_name: str,
    description: str,
    embedding_function: Any,
    host: str,
    port: int,
):
    def search_tool(query: str) -> str:
        retriever = get_retriever(collection_name, embedding_function, host, port)
        docs = retriever.invoke(query)
        return "\n\n".join(doc.page_content for doc in docs)

    return StructuredTool.from_function(
        func=search_tool,
        name=tool_name,
        description=description,
    )


def build_rag_tools(embedding_function: Any, host: str, port: int) -> dict[str, Any]:
    descriptions = {
        "research_search": (
            "Search internal research documents for product performance, revenue growth, "
            "and segment profit figures (e.g. AI products, Q2 2025)."
        ),
        "finance_search": (
            "Search internal finance documents for company profit, earnings, margins, "
            "and quarterly financial results (e.g. Q2 2025 net profit)."
        ),
        "legal_search": "Search internal legal documents for regulations and compliance.",
    }
    return {
        tool_name: make_collection_search_tool(
            tool_name,
            collection_name,
            descriptions[tool_name],
            embedding_function,
            host,
            port,
        )
        for tool_name, collection_name in COLLECTIONS.items()
    }