from django.conf import settings
from sparkai.llm.llm import ChatSparkLLM
from sparkai.core.messages import ChatMessage

def get_spark_client():
    return ChatSparkLLM(
        spark_api_url=settings.wss://spark-api.xf-yun.com/chat/pro-128k,
        spark_app_id=settings.073e07dd,
        spark_api_key=settings.89c58c9ff806b199ebb047b5781051fe,
        spark_api_secret=settings.YmRlMzg1ZWY3NTU0YTFmZmI1ODJiNjE4,
        spark_llm_domain=settings.pro-128k,
        streaming=False,
    )

def ask_spark(prompt: str) -> str:
    try:
        client = get_spark_client()
        messages = [ChatMessage(role="user", content=prompt)]
        response = client.generate([messages])
        answer = response.generations[0][0].text
        return answer.strip()
    except Exception as e:
        return f"【错误】调用星火大模型失败：{str(e)}"