import boto3
import json

bedrock_agent_runtime = boto3.client("bedrock-agent-runtime")

response = bedrock_agent_runtime.invoke_agent(
    agentId="AGENT_ID",
    agentAliasId="AGENT_ALIAS_ID",
    sessionId="test-session-123",
    inputText="Przeanalizuj ryzyko bioróżnorodności dla hexa 86392b417ffffff, resolution 6",
)

for event in response["completion"]:
    if "chunk" in event:
        print(event["chunk"]["bytes"].decode(), end="")
