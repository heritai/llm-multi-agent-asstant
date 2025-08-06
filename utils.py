"""
Utility functions for loading and creating vector stores from regulatory PDF documents.
Uses HuggingFace embeddings and Chroma for document storage and retrieval.
"""

import os
from langchain.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# --- Constants ---
DATA_DIR = "regulations-text"         # Directory containing PDF documents
VECTOR_DB_ROOT = "vector_dbs"         # Directory to store vector databases
MODEL_NAME = "all-MiniLM-L6-v2"       # Embedding model name
CHUNK_SIZE = 100                      # Size of text chunks for splitting
CHUNK_OVERLAP = 20                    # Overlap between text chunks

# Supported regulatory sources and their filenames
REGULATORY_SOURCES = {
    "gdpr": "gdpr.pdf",
    "act": "act.pdf"
}

def get_vectorstore_path(name):
    """
    Returns the path for the vector store directory for a given regulation name.
    """
    return os.path.join(VECTOR_DB_ROOT, f"{name}_index")

def load_documents(doc_name):
    """
    Loads and splits a PDF document into smaller text chunks for embedding.
    Args:
        doc_name (str): Filename of the PDF document.
    Returns:
        List of split document chunks.
    """
    path = os.path.join(DATA_DIR, doc_name)
    loader = PyPDFLoader(path)
    docs = loader.load()
    splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    return splitter.split_documents(docs)

def create_vectorstore(name, docs):
    """
    Creates a Chroma vector store from document chunks and persists it to disk.
    Args:
        name (str): Regulation name (e.g., 'gdpr', 'act').
        docs (list): List of document chunks.
    Returns:
        Chroma vector store object.
    """
    embeddings = HuggingFaceEmbeddings(model_name=MODEL_NAME)
    vectorstore = Chroma.from_documents(
        documents=docs,
        collection_name="legal_docs",
        embedding=embeddings,
        persist_directory=get_vectorstore_path(name)
    )
    vectorstore.persist()  # Save the vector store to disk
    return vectorstore

def load_vectorstore(name):
    """
    Loads an existing vector store from disk if available, otherwise creates it from the PDF.
    Args:
        name (str): Regulation name (must be in REGULATORY_SOURCES).
    Returns:
        Chroma vector store object.
    """
    embeddings = HuggingFaceEmbeddings(model_name=MODEL_NAME)
    path = get_vectorstore_path(name)
    if os.path.exists(path):
        # Load existing vector store
        return Chroma(
            persist_directory=path,
            collection_name='legal_docs',
            embedding_function=embeddings
        )
    else:
        # Create vector store from PDF if not found
        docs = load_documents(REGULATORY_SOURCES[name])
        return create_vectorstore(name, docs)