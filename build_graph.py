import json
import networkx as nx
import csv
import os
import argparse

def create_project_graph(input_json, output_dir="graph_export"):
    """
    Parses the symbol extraction JSON and builds a NetworkX directed graph.
    Nodes represent files, classes, functions, or modules.
    Edges represent 'CONTAINS' (e.g., File -> Function) or 'IMPORTS' (File -> Module).
    """
    with open(input_json, 'r') as f:
        data = json.load(f)
        
    G = nx.DiGraph()
    
    for relative_path, file_data in data.items():
        # Add a node for the file itself
        G.add_node(relative_path, type="File", label=relative_path)
        
        # Add classes within the file
        for cls in file_data.get("classes", []):
            cls_name = cls["name"]
            node_id = f"{relative_path}:{cls_name}"
            G.add_node(node_id, type="Class", label=cls_name)
            G.add_edge(relative_path, node_id, type="CONTAINS")
            
        # Add functions within the file
        for func in file_data.get("functions", []):
            func_name = func["name"]
            node_id = f"{relative_path}:{func_name}"
            G.add_node(node_id, type="Function", label=func_name)
            G.add_edge(relative_path, node_id, type="CONTAINS")
            
        # Add imports from the file
        for imp in file_data.get("imports", []):
            imp_name = imp["name"].strip()
            
            # Simple parsing of import statements
            target_name = imp_name
            if imp_name.startswith("import "):
                target_name = imp_name.replace("import ", "")
            elif imp_name.startswith("from "):
                parts = imp_name.split(" import ")
                if len(parts) == 2:
                    module_part = parts[0].replace("from ", "").strip()
                    symbol_part = parts[1].strip()
                    target_name = f"{module_part}.{symbol_part}"
            
            node_id = f"module:{target_name}"
            if not G.has_node(node_id):
                G.add_node(node_id, type="Module", label=target_name)
            
            G.add_edge(relative_path, node_id, type="IMPORTS")
            
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Export as GraphML
    graphml_path = os.path.join(output_dir, "project_graph.graphml")
    nx.write_graphml(G, graphml_path)
    print(f"Exported GraphML to {graphml_path}")
    print("  -> Compatible with Gephi, Cytoscape, and Neo4j (via APOC)")
    
    # 2. Export as CSV (Compatible with Amazon Neptune, Neo4j LOAD CSV)
    nodes_csv = os.path.join(output_dir, "nodes.csv")
    edges_csv = os.path.join(output_dir, "edges.csv")
    
    with open(nodes_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["~id", "~label", "name:String"])
        for node, attrs in G.nodes(data=True):
            writer.writerow([node, attrs.get("type", "Unknown"), attrs.get("label", node)])
            
    with open(edges_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["~id", "~from", "~to", "~label"])
        for i, (u, v, attrs) in enumerate(G.edges(data=True)):
            writer.writerow([f"e{i}", u, v, attrs.get("type", "RELATES_TO")])
            
    print(f"Exported CSVs to {nodes_csv} and {edges_csv}")
    print("  -> Compatible with Amazon Neptune Bulk Loader and standard graph DB imports")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build and export a directed graph of project relationships.")
    parser.add_argument("--input", default="test_symbols.json", help="Path to the JSON file with extracted symbols")
    parser.add_argument("--outdir", default="graph_export", help="Output directory for graph files")
    args = parser.parse_args()
    
    create_project_graph(args.input, args.outdir)
