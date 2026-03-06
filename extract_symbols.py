import os
import ast
import json
import argparse
from typing import Dict, List, Any

try:
    import tree_sitter_javascript as tsjavascript
    import tree_sitter_typescript as tstypescript
    from tree_sitter import Language, Parser, Query, QueryCursor
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False

def extract_python_symbols(filepath: str) -> Dict[str, List[Dict[str, Any]]]:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return {"classes": [], "functions": [], "imports": []}

    try:
        tree = ast.parse(content)
    except Exception:
        return {"classes": [], "functions": [], "imports": []}

    classes = []
    functions = []
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.append({"name": node.name, "line": node.lineno})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append({"name": node.name, "line": node.lineno})
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({"name": f"import {alias.name}", "line": node.lineno})
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append({"name": f"from {module} import {alias.name}", "line": node.lineno})

    return {
        "classes": sorted(classes, key=lambda x: x["line"]),
        "functions": sorted(functions, key=lambda x: x["line"]),
        "imports": sorted(imports, key=lambda x: x["line"])
    }

def extract_js_ts_symbols(filepath: str, is_ts: bool) -> Dict[str, List[Dict[str, Any]]]:
    if not HAS_TREE_SITTER:
        return {"classes": [], "functions": [], "imports": [], "error": "tree-sitter not installed"}

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return {"classes": [], "functions": [], "imports": []}
        
    content_bytes = content.encode('utf-8')

    if is_ts:
        lang = Language(tstypescript.language_typescript())
    else:
        lang = Language(tsjavascript.language())

    parser = Parser(lang)
    tree = parser.parse(content_bytes)

    query_str = """
    (class_declaration name: (identifier) @class_name)
    (function_declaration name: (identifier) @function_name)
    (method_definition name: (property_identifier) @method_name)
    (variable_declarator 
        name: (identifier) @arrow_func_name 
        value: [(arrow_function) (function_expression)]
    )
    (import_statement) @import_stmt
    """
    
    try:
        query = Query(lang, query_str)
        cursor = QueryCursor(query)
        matches = cursor.matches(tree.root_node)
    except Exception as e:
        print(f"Error executing tree-sitter query on {filepath}: {e}")
        return {"classes": [], "functions": [], "imports": []}
    
    classes = []
    functions = []
    imports = []

    for match_index, captures in matches:
        for capture_name, nodes in captures.items():
            for node in nodes:
                try:
                    node_text = node.text.decode('utf-8')
                except Exception:
                    node_text = ""
                    
                if capture_name == "class_name":
                    classes.append({"name": node_text, "line": node.start_point[0] + 1})
                elif capture_name in ["function_name", "method_name", "arrow_func_name"]:
                    functions.append({"name": node_text, "line": node.start_point[0] + 1})
                elif capture_name == "import_stmt":
                    import_text = node_text.split('\n')[0][:100] # get first line snippet max 100 chars
                    imports.append({"name": import_text, "line": node.start_point[0] + 1})

    def unique_sorted(items):
        seen = set()
        res = []
        for item in sorted(items, key=lambda x: x["line"]):
            key = (item["name"], item["line"])
            if key not in seen:
                seen.add(key)
                res.append(item)
        return res

    return {
        "classes": unique_sorted(classes),
        "functions": unique_sorted(functions),
        "imports": unique_sorted(imports)
    }

def main():
    parser = argparse.ArgumentParser(description="Extract symbols from Python and JS/TS files")
    parser.add_argument("directory", help="Directory to traverse")
    parser.add_argument("-o", "--output", default="symbols.json", help="Output JSON file")
    args = parser.parse_args()

    results = {}
    
    # If the user passed a single file instead of a directory
    if os.path.isfile(args.directory):
        files_to_process = [(args.directory, '')]
    else:
        files_to_process = []
        for root, dirs, files in os.walk(args.directory):
            # Exclude hidden directories, virtual environments, node_modules etc.
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('venv', 'node_modules', '__pycache__')]
            for file in files:
                files_to_process.append((os.path.join(root, file), file))

    for filepath, file in files_to_process:
        ext = os.path.splitext(filepath)[1].lower()
            
        if ext == '.py':
            symbols = extract_python_symbols(filepath)
            if symbols["classes"] or symbols["functions"] or symbols["imports"]:
                results[filepath] = symbols
        elif ext in ['.js', '.jsx']:
            symbols = extract_js_ts_symbols(filepath, is_ts=False)
            if symbols.get("classes") or symbols.get("functions") or symbols.get("imports"):
                results[filepath] = symbols
        elif ext in ['.ts', '.tsx']:
            symbols = extract_js_ts_symbols(filepath, is_ts=True)
            if symbols.get("classes") or symbols.get("functions") or symbols.get("imports"):
                results[filepath] = symbols

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)

    print(f"Extraction complete. Found symbols in {len(results)} files. Results saved to {args.output}")

if __name__ == "__main__":
    main()
