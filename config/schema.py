import os
import json
from typing import Dict, List, Optional
from pydantic import BaseModel
from dotenv import load_dotenv
from nebula3.gclient.net import ConnectionPool
from nebula3.Config import Config
from config.settings import settings

load_dotenv()


class NodeInfo(BaseModel):
    """节点信息模型"""

    properties: List[str] = []  # 节点属性列表
    out_relation: List[str] = []  # 出边关系，格式: (n)-[:r]->(t)
    in_relation: List[str] = []  # 入边关系，格式: (s)-[:r]->(n)
    sample: Dict[str, str] = {}  # 样本数据


class NebulaSchema(BaseModel):
    """Nebula图数据库Schema模型"""

    schema: Dict[str, NodeInfo] = {}  # 节点类型及其完整信息


class NebulaSchemaExtractor:
    """Nebula Schema提取器"""

    def __init__(self):
        self.config = Config()
        self.config.max_connection_pool_size = 10
        self.config.timeout = 10000
        self.config.port = int(settings.nebula["port"])
        self.config.address = settings.nebula["host"]
        self.config.user = settings.nebula["user"]
        self.config.password = settings.nebula["password"]

        self.conn = ConnectionPool()
        self.conn.init([(self.config.address, self.config.port)], self.config)
        self.session = None

    def connect(self):
        """建立连接"""
        try:
            self.session = self.conn.get_session(
                user_name=self.config.user, password=self.config.password
            )
            result = self.session.execute(f"USE {settings.nebula['space']}")
            if not result.is_succeeded():
                raise Exception(f"Failed to use space: {result.error_msg()}")
            print(f"Successfully connected to Nebula space: {settings.nebula['space']}")
        except Exception as e:
            raise Exception(f"Failed to connect to Nebula: {str(e)}")

    def get_node_types_and_properties(self) -> Dict[str, List[str]]:
        """获取所有节点类型及其属性"""
        node_types = {}

        try:
            # 获取所有标签
            result = self.session.execute("SHOW TAGS")
            if not result.is_succeeded():
                raise Exception(f"Failed to show tags: {result.error_msg()}")
            result = result.as_primitive()

            # 遍历每个标签获取属性
            for row in result:
                tag_name = row["Name"]
                # 获取标签的属性
                desc_result = self.session.execute(
                    f"DESCRIBE TAG `{tag_name}`"
                ).as_primitive()
                if desc_result:
                    properties = [prop["Field"] for prop in desc_result]
                    node_types[tag_name] = properties

            print(f"Found {len(node_types)} node types")
            return node_types

        except Exception as e:
            print(f"Error getting node types: {str(e)}")
            return {}

    def get_edge_types(self) -> List[str]:
        """获取所有边类型"""
        try:
            result = self.session.execute("SHOW EDGES")
            if not result.is_succeeded():
                raise Exception(f"Failed to show edges: {result.error_msg()}")
            result = result.as_primitive()
            edge_types = []
            for row in result:
                edge_name = row["Name"]
                edge_types.append(edge_name)

            print(f"Found {len(edge_types)} edge types")
            return edge_types

        except Exception as e:
            print(f"Error getting edge types: {str(e)}")
            return []

    def get_node_relations(
        self, node_types: List[str], edge_types: List[str]
    ) -> Dict[str, Dict[str, List[str]]]:
        """获取每个节点类型的关系"""
        relations = {}

        for node_type in node_types:
            relations[node_type] = {"out_relation": [], "in_relation": []}

            # 查找出边关系
            for edge_type in edge_types:
                try:
                    # 查询该节点类型作为源节点的边
                    query = f"""
                    MATCH (n:`{node_type}`)-[:`{edge_type}`]->(m)
                    RETURN DISTINCT labels(m) AS target_labels
                    LIMIT 5
                    """
                    result = self.session.execute(query).as_primitive()

                    if len(result) > 0:
                        for row in result:
                            target_labels = row["TargetLabels"]
                            for label in target_labels:
                                target_label = label
                                relation_str = f"(n)-[:{edge_type}]->({target_label})"
                                if (
                                    relation_str
                                    not in relations[node_type]["out_relation"]
                                ):
                                    relations[node_type]["out_relation"].append(
                                        relation_str
                                    )

                    # 查询该节点类型作为目标节点的边
                    query = f"""
                    MATCH (m)-[:`{edge_type}`]->(n:`{node_type}`)
                    RETURN DISTINCT labels(m) AS source_labels
                    LIMIT 5
                    """
                    result = self.session.execute(query).as_primitive()

                    if len(result) > 0:
                        for row in result:
                            source_labels = row["SourceLabels"]
                            for label in source_labels:
                                source_label = label
                                relation_str = f"({source_label})-[:{edge_type}]->(n)"
                                if (
                                    relation_str
                                    not in relations[node_type]["in_relation"]
                                ):
                                    relations[node_type]["in_relation"].append(
                                        relation_str
                                    )

                except Exception as e:
                    print(
                        f"Error getting relations for {node_type}-{edge_type}: {str(e)}"
                    )
                    continue

        return relations

    def get_sample_data(
        self, node_types: Dict[str, List[str]]
    ) -> Dict[str, Dict[str, str]]:
        """获取每个节点类型的样本数据"""
        samples = {}

        for node_type, properties in node_types.items():
            try:
                # 获取一个样本节点
                query = f"MATCH (n:`{node_type}`) RETURN n LIMIT 1"
                result = self.session.execute(query).as_primitive()

                if len(result) > 0:
                    node_data = result[0]["n"]
                    sample_props = {}

                    # 提取属性值
                    for prop in properties:
                        if prop in node_data:
                            value = node_data[prop]
                            # 转换为字符串表示
                            sample_props[prop] = value

                    samples[node_type] = sample_props

            except Exception as e:
                print(f"Error getting sample for {node_type}: {str(e)}")
                samples[node_type] = {}

        return samples

    def extract_schema(self) -> NebulaSchema:
        """提取完整的schema"""
        print("Starting schema extraction...")

        # 连接数据库
        self.connect()

        # 获取节点类型和属性
        print("Getting node types and properties...")
        node_types = self.get_node_types_and_properties()

        # 获取边类型
        print("Getting edge types...")
        edge_types = self.get_edge_types()

        # 获取节点关系
        print("Getting node relations...")
        node_relations = self.get_node_relations(list(node_types.keys()), edge_types)

        # 获取样本数据
        print("Getting sample data...")
        sample_data = self.get_sample_data(node_types)

        # 构建schema字典
        schema_dict = {}
        for node_type in node_types.keys():
            schema_dict[node_type] = NodeInfo(
                properties=node_types[node_type],
                out_relation=node_relations.get(node_type, {}).get("out_relation", []),
                in_relation=node_relations.get(node_type, {}).get("in_relation", []),
                sample=sample_data.get(node_type, {}),
            )

        # 创建schema对象
        schema = NebulaSchema(schema=schema_dict)

        print("Schema extraction completed!")
        return schema

    def save_schema(
        self, schema: NebulaSchema, file_path: str = "config/nebula_schema.json"
    ):
        """保存schema到文件"""
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(schema.model_dump(), f, indent=2, ensure_ascii=False)
            print(f"Schema saved to {file_path}")
        except Exception as e:
            print(f"Error saving schema: {str(e)}")

    def close(self):
        """关闭连接"""
        if self.session:
            self.session.release()
        if self.conn:
            self.conn.close()


def main():
    """主函数"""
    extractor = NebulaSchemaExtractor()

    try:
        # 提取schema
        schema = extractor.extract_schema()

        # 保存schema
        extractor.save_schema(schema)

        # 打印摘要
        print("\n=== Schema Summary ===")
        print(f"Node types: {len(schema.schema)}")
        for node_type, node_info in schema.schema.items():
            print(f"  - {node_type}: {len(node_info.properties)} properties")

        print(f"\nRelations:")
        for node_type, node_info in schema.schema.items():
            total_relations = len(node_info.out_relation) + len(node_info.in_relation)
            if total_relations > 0:
                print(
                    f"  - {node_type}: {len(node_info.out_relation)} outgoing, {len(node_info.in_relation)} incoming"
                )

    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        extractor.close()


if __name__ == "__main__":
    main()
