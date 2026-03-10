import os
import ast
import argparse

try:
    import chromadb
    from sentence_transformers import SentenceTransformer
    from rank_bm25 import BM25Okapi
    from dotenv import load_dotenv
    from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    
    # Load environment variables (to grab the HF Token)
    load_dotenv()
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

def get_node_source(node, source_lines):
    # Extracts the full source code for an AST node using lines
    # node.lineno is 1-indexed, node.end_lineno is 1-indexed
    start = node.lineno - 1
    end = node.end_lineno
    return "\n".join(source_lines[start:end])

def extract_chunks(filepath):
    """
    Extracts chunks (classes and functions) from a Python file.
    Returns a list of dicts containing text and metadata.
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            source_lines = content.split('\n')
    except Exception:
        return []

    try:
        tree = ast.parse(content)
    except Exception:
        return []

    chunks = []
    
    # We will traverse top-level and class-level methods
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            code = get_node_source(node, source_lines)
            chunks.append({
                "text": code,
                "metadata": {
                    "filepath": filepath,
                    "name": node.name,
                    "type": "class",
                    "start_line": node.lineno,
                    "end_line": node.end_lineno
                }
            })
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            code = get_node_source(node, source_lines)
            chunks.append({
                "text": code,
                "metadata": {
                    "filepath": filepath,
                    "name": node.name,
                    "type": "function",
                    "start_line": node.lineno,
                    "end_line": node.end_lineno
                }
            })
            
    return chunks

def build_vector_db(directory, db_path="chroma_db", collection_name="codebase"):
    if not HAS_DEPS:
        print("Please install chromadb and sentence-transformers first!")
        return None, None
        
    print(f"Initializing ChromaDB at {db_path}...")
    client = chromadb.PersistentClient(path=db_path)
    
    # Using a popular lightweight code embedding model from HuggingFace
    print("Loading HuggingFace embedding model (all-MiniLM-L6-v2) ... this might take a minute on the first run to download...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    
    # Create or get collection
    try:
        collection = client.get_collection(name=collection_name)
        print(f"Collection '{collection_name}' already exists, clearing it for a fresh index...")
        client.delete_collection(name=collection_name)
    except Exception:
        pass
        
    collection = client.create_collection(name=collection_name)
    
    # Gather chunks
    all_chunks = []
    # If a single file
    if os.path.isfile(directory) and directory.endswith('.py'):
        all_chunks.extend(extract_chunks(directory))
    else:
        for root, dirs, files in os.walk(directory):
            # Exclude common non-source directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('venv', 'node_modules', '__pycache__', 'chroma_db', 'graph_export')]
            for file in files:
                if file.endswith('.py'):
                    filepath = os.path.join(root, file)
                    all_chunks.extend(extract_chunks(filepath))
                
    if not all_chunks:
        print("No Python classes or functions found to index.")
        return collection, model
        
    print(f"Extracted {len(all_chunks)} chunks (classes/functions). Generating embeddings and indexing...")
    
    texts = [chunk["text"] for chunk in all_chunks]
    metadatas = [chunk["metadata"] for chunk in all_chunks]
    ids = [f"{chunk['metadata']['filepath']}::{chunk['metadata']['name']}::{i}" for i, chunk in enumerate(all_chunks)]
    
    # Generate embeddings
    embeddings = model.encode(texts).tolist()
    
    # Add to ChromaDB
    # Chroma requires metadata values to be str, int, float, or bool
    for meta in metadatas:
        for key in list(meta.keys()):
            if meta[key] is None:
                meta[key] = ""
    
    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas
    )
    
    print("Indexing complete! Data stored in ChromaDB.")
    
    # Generate the BM25 model for the exact same chunks
    tokenized_corpus = [doc.lower().split(" ") for doc in texts]
    bm25_model = BM25Okapi(tokenized_corpus)
    
    return collection, model, bm25_model, all_chunks

def search_codebase(query, collection, model, bm25_model, all_chunks, top_k=2):
    print(f"\n=============================================")
    print(f"🔎 HYBRID SEARCHING FOR: '{query}'")
    print(f"=============================================")
    
    matched_docs = []
    
    # 1. SEMANTIC SEARCH LOGIC
    query_embedding = model.encode([query]).tolist()
    semantic_results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k
    )
    
    if semantic_results['documents'] and semantic_results['documents'][0]:
        print("\n--- Semantic Results (Intent Matching) ---")
        for i in range(len(semantic_results['documents'][0])):
            metadata = semantic_results['metadatas'][0][i]
            doc = semantic_results['documents'][0][i]
            matched_docs.append(doc)
            print(f"🎯 Semantic Match: {metadata['filepath']} | {metadata['type']} {metadata['name']}")
            print('\n'.join(doc.split('\n')[:4]) + "\n...")
            
    # 2. KEYWORD (BM25) SEARCH LOGIC
    tokenized_query = query.lower().split(" ")
    bm25_scores = bm25_model.get_scores(tokenized_query)
    
    # Sort BM25 chunks cleanly
    top_bm25_indexes = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:top_k]
    
    print("\n--- Keyword Results (Exact/Sub-string Matching) ---")
    for idx in top_bm25_indexes:
        if bm25_scores[idx] > 0: # Only if it's a real match
            chunk = all_chunks[idx]
            matched_docs.append(chunk["text"])
            meta = chunk["metadata"]
            print(f"🔑 Keyword Match: {meta['filepath']} | {meta['type']} {meta['name']} (Score: {bm25_scores[idx]:.2f})")
            print('\n'.join(chunk["text"].split('\n')[:4]) + "\n...")
            
    # Remove duplicates from the list exactly matching
    matched_docs = list(set(matched_docs))
            
    # 3. AI GENERATED SUMMARY
    if not matched_docs:
        print("No matches were identified in the codebase.")
        return
        
    print("\n--- AI Generating Summary of Context ---")
    
    api_key = os.environ.get("HUGGINGFACEHUB_API_TOKEN")
    if not api_key:
        print("⚠ HUGGINGFACEHUB_API_TOKEN environment variable not set. Skipping AI summary analysis.")
        return
        
    combined_context = "\n\n=== CODE BLOCK ===\n".join(matched_docs)
    
    prompt_template = """
    A user has searched a codebase with the query: "{query}"

    Here are the isolated sections of the code that matched hybrid logic (Keywords and Intents):
    {context}

    Based heavily on the provided text, what is the answer to the user's query? 
    Briefly explain how these code blocks fit directly into answering what they requested. Do not make up answers. Keep it highly concise.
    """

    prompt = ChatPromptTemplate.from_template(prompt_template)
    
    # Instantiate the LLM 
    llm = HuggingFaceEndpoint(
        repo_id="Qwen/Qwen2.5-72B-Instruct",
        huggingfacehub_api_token=api_key,
        task="conversational",
        temperature=0.1,
        max_new_tokens=1024,
        return_full_text=False
    )
    chat_model = ChatHuggingFace(llm=llm)
    chain = prompt | chat_model | StrOutputParser()
    
    try:
        response = chain.invoke({
            "query": query,
            "context": combined_context
        })
        print(f"\n🤖 AI Summary:\n{response}\n")
    except Exception as e:
        print(f"\n❌ Error contacting HuggingFace LLM: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Semantic Code Search Pipeline")
    parser.add_argument("directory", nargs="?", default=".", help="Directory to parse and index")
    parser.add_argument("--query", "-q", type=str, help="Search query to run after indexing")
    parser.add_argument("--db-path", default="chroma_db", help="Path to store the vector database")
    args = parser.parse_args()
    
    collection, model, bm25_model, all_chunks = build_vector_db(args.directory, db_path=args.db_path)
    
    if collection and model and bm25_model:
        if args.query:
            search_codebase(args.query, collection, model, bm25_model, all_chunks)
        else:
            # Run some default test queries
            print("\nRunning sample semantic searches...")
            search_codebase("How is the GitHub URL validated?", collection, model, bm25_model, all_chunks)
            search_codebase("where is the login logic?", collection, model, bm25_model, all_chunks)
