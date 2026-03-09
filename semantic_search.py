import os
import ast
import argparse

try:
    import chromadb
    from sentence_transformers import SentenceTransformer
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
    return collection, model

def search_codebase(query, collection, model, top_k=3):
    print(f"\n=============================================")
    print(f"🔎 SEARCHING FOR: '{query}'")
    print(f"=============================================")
    
    query_embedding = model.encode([query]).tolist()
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k
    )
    
    if not results['documents'][0]:
        print("No results found.")
        return
        
    for i in range(len(results['documents'][0])):
        score = results['distances'][0][i] if 'distances' in results and results['distances'] else "N/A"
        metadata = results['metadatas'][0][i]
        doc = results['documents'][0][i]
        
        print(f"\n🎯 Result {i+1} (Distance: {score:.4f}):")
        print(f"   File: {metadata['filepath']} | Type: {metadata['type']} | Name: {metadata['name']} | Lines: {metadata['start_line']}-{metadata['end_line']}")
        print("-" * 60)
        # Print a snippet of the code
        lines = doc.split('\n')
        snippet = '\n'.join(lines[:10])
        print(snippet)
        if len(lines) > 10:
            print("   ...")
        print("-" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Semantic Code Search Pipeline")
    parser.add_argument("directory", nargs="?", default=".", help="Directory to parse and index")
    parser.add_argument("--query", "-q", type=str, help="Search query to run after indexing")
    parser.add_argument("--db-path", default="chroma_db", help="Path to store the vector database")
    args = parser.parse_args()
    
    collection, model = build_vector_db(args.directory, db_path=args.db_path)
    
    if collection and model:
        if args.query:
            search_codebase(args.query, collection, model)
        else:
            # Run some default test queries
            print("\nRunning sample semantic searches...")
            search_codebase("How is the GitHub URL validated?", collection, model)
            search_codebase("Database settings and background workers", collection, model)
