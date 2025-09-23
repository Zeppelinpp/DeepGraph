from tavily import TavilyClient
from pydantic import BaseModel
from openai import AsyncOpenAI
from config.settings import settings

search_client = TavilyClient(api_key=settings.tavily_key)


class SearchResult(BaseModel):
    url: str
    title: str
    content: str

    def to_md(self):
        md = []
        md.append(f"## {self.title}")
        md.append(f"- `url`: {self.url}")
        md.append(f"- `content`: {self.content[:500]}...")
        return "\n".join(md)


async def search_web(query: str):
    response = search_client.search(query)
    results = []
    for result in response["results"]:
        result = SearchResult(
            url=result["url"],
            title=result["title"],
            content=result["content"],
        )
        results.append(result.to_md())

    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )
    response = await client.chat.completions.create(
        model="qwen-turbo",
        messages=[
            {
                "role": "system",
                "content": "根据查询的原始Query和查询结果, 总结一个精炼的摘要, 用于回答用户的问题",
            },
            {
                "role": "user",
                "content": f"原始Query: {query}\n查询结果: \n{'\n'.join(results)}",
            },
        ],
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(search_web("财务分析中的成本分析框架是什么"))
    print(result)
