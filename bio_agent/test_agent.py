import boto3
import json

bedrock_agent_runtime = boto3.client("bedrock-agent-runtime")

response = bedrock_agent_runtime.invoke_agent(
    agentId="071U4I1ZLH",
    agentAliasId="ie-bio-agent",
    sessionId="test-session-123",
    inputText="Przeanalizuj ryzyko bioróżnorodności dla hexa 86392b417ffffff, resolution 6",
)

for event in response["completion"]:
    if "chunk" in event:
        print(event["chunk"]["bytes"].decode(), end="")
