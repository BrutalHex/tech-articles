import env_setup  # noqa: F401 — load .env and endpoints first

from langchain_chroma import Chroma
from langchain_core.documents import Document
from env_setup import CHROMA_HOST, CHROMA_PORT
from openai_config import create_embeddings, verify_openai_connectivity


def seed_collection(
    collection_name: str,
    documents: list[Document],
    embedding_function,
    host: str,
    port: int,
):
    """Replace a collection with fresh documents."""
    existing = Chroma(
        collection_name=collection_name,
        embedding_function=embedding_function,
        host=host,
        port=port,
    )
    try:
        existing.delete_collection()
    except Exception:
        pass

    vectorstore = Chroma(
        collection_name=collection_name,
        embedding_function=embedding_function,
        host=host,
        port=port,
    )
    vectorstore.add_documents(documents)
    print(f"✅ Seeded {len(documents)} documents into '{collection_name}'")


if __name__ == "__main__":
    verify_openai_connectivity()
    embeddings = create_embeddings()

    # Research: growth rates and market drivers (no dollar revenue figures).
    research_docs = [
        Document(
            page_content=(
                "Q2 2025 AI Products — Growth Analysis: Revenue grew 23% year-over-year in "
                "the second quarter of 2025. Primary growth drivers were (1) enterprise "
                "adoption of the ML inference platform, (2) expansion into healthcare "
                "verticals, and (3) a bundled pricing model that increased average contract "
                "value by 18%."
            ),
            metadata={"source": "Q2_Growth_Analysis.pdf", "type": "research"},
        ),
    ]

    # Finance: revenue and earnings figures (no growth-driver narrative).
    finance_docs = [
        Document(
            page_content=(
                "Q2 2025 AI Products — Revenue Report: The AI products segment recorded "
                "$62 million in revenue for the second quarter of 2025. Total company "
                "revenue was $210 million. Net profit was $48 million with operating "
                "margins of 31%."
            ),
            metadata={"source": "Q2_Revenue_Report.pdf", "type": "financial"},
        ),
    ]

    legal_docs = [
        Document(
            page_content="The new EU AI Act requires high-risk AI systems to undergo conformity assessments before deployment.",
            metadata={"source": "EU_AI_Act_Summary.pdf", "type": "legal"},
        )
    ]

    for name, docs in [
        ("research_docs", research_docs),
        ("finance_docs", finance_docs),
        ("legal_docs", legal_docs),
    ]:
        seed_collection(name, docs, embeddings, CHROMA_HOST, CHROMA_PORT)

    print("\n🎉 All collections have been seeded successfully!")
    print("  finance_docs  → AI product revenue ($62M), net profit, margins")
    print("  research_docs → 23% YoY growth + growth drivers")