from nebula3.Config import Config
from nebula3.gclient.net import ConnectionPool
from config.settings import settings
from typing import Any, List, Dict


def execute_ngql(ngql: str) -> Any:
    """
    Execute nGQL query and return result
    """
    config = Config()
    config.max_connection_pool_size = 10
    config.timeout = 10000
    config.port = settings.nebula["port"]
    config.address = settings.nebula["host"]
    config.user = settings.nebula["user"]
    config.password = settings.nebula["password"]

    conn = ConnectionPool()
    conn.init([(config.address, config.port)], config)

    session = conn.get_session(user_name=config.user, password=config.password)
    session.execute(f"USE {settings.nebula['space']}")

    ngql = ngql.strip()
    if ngql.startswith("```"):
        ngql = ngql.strip("```sql\n").strip("```").strip()

    result = session.execute(ngql).as_primitive()
    return result

def get_schema(node_types: List[str]) -> Dict[str, Any]:
    """
    Get schema information for specified node types
    
    Args:
        node_types: List of node type names
        
    Returns:
        Dictionary with node_type as key and schema info as value
        Format: {node_type: {"properties": [], "out_relation": [], "in_relation": [], "sample": {}}}
    """
    config = Config()
    config.max_connection_pool_size = 10
    config.timeout = 10000
    config.port = settings.nebula["port"]
    config.address = settings.nebula["host"]
    config.user = settings.nebula["user"]
    config.password = settings.nebula["password"]

    conn = ConnectionPool()
    conn.init([(config.address, config.port)], config)

    session = conn.get_session(user_name=config.user, password=config.password)
    session.execute(f"USE {settings.nebula['space']}")
    
    try:
        schema_info = {}
        
        for node_type in node_types:
            schema_info[node_type] = {
                "properties": [],
                "out_relation": [],
                "in_relation": [],
                "sample": {}
            }
            
            # Get node properties
            try:
                desc_result = session.execute(f"DESCRIBE TAG `{node_type}`").as_primitive()
                if desc_result:
                    properties = [prop["Field"] for prop in desc_result]
                    schema_info[node_type]["properties"] = properties
            except Exception as e:
                schema_info[node_type]["properties"] = []
            
            # Get outgoing relations - directly match any edge from this node type
            try:
                query = f"""
                MATCH (n:`{node_type}`)-[r]->(m)
                RETURN DISTINCT type(r) AS edge_type, labels(m) AS target_labels
                LIMIT 50
                """
                result = session.execute(query).as_primitive()
                
                for row in result:
                    edge_type = row["edge_type"]
                    target_labels = row["target_labels"]
                    for label in target_labels:
                        relation_str = f"(n)-[:{edge_type}]->({label})"
                        if relation_str not in schema_info[node_type]["out_relation"]:
                            schema_info[node_type]["out_relation"].append(relation_str)
                            
            except Exception as e:
                continue
            
            # Get incoming relations - directly match any edge to this node type
            try:
                query = f"""
                MATCH (m)-[r]->(n:`{node_type}`)
                RETURN DISTINCT type(r) AS edge_type, labels(m) AS source_labels
                LIMIT 50
                """
                result = session.execute(query).as_primitive()
                
                for row in result:
                    edge_type = row["edge_type"]
                    source_labels = row["source_labels"]
                    for label in source_labels:
                        relation_str = f"({label})-[:{edge_type}]->(n)"
                        if relation_str not in schema_info[node_type]["in_relation"]:
                            schema_info[node_type]["in_relation"].append(relation_str)
                            
            except Exception as e:
                continue
            
            # Get sample data
            try:
                query = f"MATCH (n:`{node_type}`) RETURN n LIMIT 1"
                result = session.execute(query).as_primitive()
                
                if len(result) > 0:
                    node_data = result[0]["n"]
                    # Extract sample properties
                    sample_props = {}
                    for prop_name, prop_value in node_data.items():
                        sample_props[prop_name] = prop_value
                    schema_info[node_type]["sample"] = sample_props
                    
            except Exception as e:
                schema_info[node_type]["sample"] = {}
        
        return schema_info
        
    except Exception as e:
        print(f"Error getting schema: {str(e)}")
        return {}
    finally:
        session.release()
        conn.close()


if __name__ == "__main__":
    # Example usage - replace with actual node types from your graph
    print(get_schema(["科目余额", "会计科目"]))