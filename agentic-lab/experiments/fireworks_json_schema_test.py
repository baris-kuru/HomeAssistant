import os

from openai import OpenAI
from pydantic import BaseModel


class Result(BaseModel):
    winner: str


def main() -> None:
    api_key = os.environ.get("FIREWORKS_API_KEY")
    if not api_key:
        raise RuntimeError("FIREWORKS_API_KEY is not set")

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.fireworks.ai/inference/v1",
    )

    response = client.chat.completions.create(
        model="accounts/fireworks/models/kimi-k2p5",
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "Result",
                "schema": Result.model_json_schema(),
            },
        },
        messages=[
            {
                "role": "user",
                "content": "Who won the US presidential election in 2012? Reply in JSON format.",
            }
        ],
    )

    print(response.choices[0].message.content)


if __name__ == "__main__":
    main()
