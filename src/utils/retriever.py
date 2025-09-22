import orjson

class KnowledgeRetriever:
    def __init__(self, persist_directory: str):
        self.persist_directory = persist_directory
        

    def retrieve(self, query: str):
        with open(self.persist_directory, "r") as f:
            data = orjson.loads(f.read())
        if query in data:
            return data[query]["framework"]
        else:
            return "暂无相关知识"

if __name__ == "__main__":
    retriever = KnowledgeRetriever(persist_directory="config/analysis_frame.json")
    print(retriever.retrieve("费用分析"))