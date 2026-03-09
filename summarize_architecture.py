import os
import argparse
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

def get_directory_structure(rootdir, max_depth=2):
    """Returns a string representation of the directory structure."""
    structure = []
    
    start_depth = rootdir.rstrip(os.path.sep).count(os.path.sep)
    for root, dirs, files in os.walk(rootdir):
        depth = root.count(os.path.sep) - start_depth
        if depth > max_depth:
            del dirs[:]
            continue
            
        # Ignore common non-source directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('venv', 'node_modules', '__pycache__', 'chroma_db', 'graph_export')]
        
        indent = '  ' * depth
        structure.append(f"{indent}- {os.path.basename(root)}/")
        
        for file in files:
            if not file.startswith('.') and file.endswith(('.py', '.js', '.ts', '.md', '.json', '.txt')):
                structure.append(f"{indent}  - {file}")
                
    return '\n'.join(structure)

def get_entry_points(rootdir):
    """Finds and reads likely entry point files."""
    entry_point_names = ['main.py', 'app.py', 'index.js', 'index.ts', 'server.js']
    entry_points_content = {}
    
    for root, dirs, files in os.walk(rootdir):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('venv', 'node_modules', '__pycache__', 'chroma_db', 'graph_export')]
        for file in files:
            if file in entry_point_names:
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        entry_points_content[filepath] = f.read()
                except Exception:
                    pass
                    
    return entry_points_content

def load_graph_relationships(edges_csv_path):
    """Loads a summary of the dependency graph from Step 3."""
    if not os.path.exists(edges_csv_path):
        return f"Dependency graph not found at '{edges_csv_path}'."
        
    try:
        with open(edges_csv_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            if len(lines) > 500:
                lines = lines[:500] + ["... (truncated for context limit)"]
            return "".join(lines)
    except Exception as e:
        return f"Error loading graph: {e}"

def generate_architecture_summary(directory, edges_csv_path, api_key=None):
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")
    
    if not api_key:
        print("\nERROR: OPENAI_API_KEY is not set.")
        print("Please provide an API key using the --api-key flag or the OPENAI_API_KEY environment variable.")
        print("Example: python summarize_architecture.py --api-key sk-xxxx...")
        return
        
    print(f"Directory Structure from '{directory}'...")
    dir_structure = get_directory_structure(directory)
    
    print("\nReading Entry Points...")
    entry_points = get_entry_points(directory)
    print(f"Identified {len(entry_points)} entry point(s).")
    
    print("\nLoading Dependency Graph...")
    graph_data = load_graph_relationships(edges_csv_path)
    
    # Format entry points for the LLM
    entry_points_str = ""
    for filepath, content in entry_points.items():
        entry_points_str += f"\n--- {filepath} ---\n"
        
        # We enforce a truncation to avoid exceeding LLM context windows
        lines = content.split('\n')
        if len(lines) > 300:
            lines = lines[:300] + ["... (truncated to center constraints)"]
            
        entry_points_str += "\n".join(lines)
        
    prompt_template = """
You are an expert system application architect. Below is information parsed from a repository.
Provide a high-level architectural summary based on these references.

1. **Top-Level Directory Structure**:
{directory_structure}

2. **Source Code from the Entry Points**:
{entry_points}

3. **Symbol Dependency/Relationship Graph (from Step 3 edges.csv)**:
{graph_data}


INSTRUCTIONS:
Reflect on the above codebase materials and generate a well-structured Markdown summary including:
- **System Overview**: High-level explanation of this repository's primary goals or services.
- **Core Components**: Identify the major files or modules and explain what they are responsible for.
- **Execution Flow**: Describe how data runs from the entry points out.
- **Notable Architectural Patterns**: Mention any key design choices or frameworks visible in these files.
"""

    prompt = ChatPromptTemplate.from_template(prompt_template)
    
    # Utilize the GPT-4o model requested
    llm = ChatOpenAI(model="gpt-4o", openai_api_key=api_key, temperature=0.1)
    
    chain = prompt | llm | StrOutputParser()
    
    print("\n=======================================================")
    print("Requesting architectural summary from LangChain -> GPT-4o...")
    print("=======================================================\n")
    
    try:
        response = chain.invoke({
            "directory_structure": dir_structure,
            "entry_points": entry_points_str,
            "graph_data": graph_data
        })
        print(response)
        
        # Save output to a file
        summary_path = os.path.join(directory, "architecture_summary.md")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(response)
        print(f"\n✅ Summary fully generated and exported to {summary_path}")
        
    except Exception as e:
        print(f"Error during LLM invocation. Ensure your API key is valid: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LangChain Pipeline: Automate High-Level Architecture Summaries")
    parser.add_argument("directory", nargs="?", default=".", help="Directory to analyze")
    parser.add_argument("--edges", default="graph_export/edges.csv", help="Path to the edges.csv graph file")
    parser.add_argument("--api-key", help="OpenAI API Key (or set OPENAI_API_KEY environment variable)")
    
    args = parser.parse_args()
    
    generate_architecture_summary(args.directory, args.edges, args.api_key)
