import orjson


class KnowledgeRetriever:
    def __init__(self, persist_directory: str):
        self.persist_directory = persist_directory

    def retrieve(self, query: str):
        with open(self.persist_directory, "r", encoding="utf-8") as f:
            content = f.read()
            try:
                data = orjson.loads(content)
            except (orjson.JSONDecodeError, TypeError):
                import json
                data = json.loads(content)
        if query in data:
            return data[query]["framework"]
        else:
            return "暂无相关知识"


if __name__ == "__main__":
    retriever = KnowledgeRetriever(persist_directory="config/analysis_frame.json")
    print(retriever.retrieve("费用分析"))
