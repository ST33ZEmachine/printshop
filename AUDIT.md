# Agent Code Audit Report

## Executive Summary
This audit reviews the BigQuery natural language agent implementation. The code demonstrates a solid foundation with MCP integration and Gemini API usage, but several critical issues and improvements are identified.

## Critical Issues

### 1. **Tool Schema Conversion (Line 52)**
**Issue**: Using `tool.inputSchema` directly may not match Gemini's expected format.

**Problem**: According to Google GenAI Python SDK documentation, `FunctionDeclaration` expects `parameters_json_schema` (a dict), not `parameters`. The MCP `inputSchema` might be a JSON Schema object that needs proper conversion.

**Recommendation**: 
```python
# Convert MCP schema to Gemini format
if isinstance(tool.inputSchema, dict):
    parameters = tool.inputSchema
else:
    # Handle if inputSchema is a JSON Schema object
    parameters = tool.inputSchema.model_dump() if hasattr(tool.inputSchema, 'model_dump') else dict(tool.inputSchema)
    
func_decl = types.FunctionDeclaration(
    name=tool.name,
    description=tool.description,
    parameters_json_schema=parameters  # Use parameters_json_schema
)
```

### 2. **Function Response Format (Line 101)**
**Issue**: Hardcoded `{"result": tool_output}` may not match what the function expects.

**Problem**: The response format should match the function's return type. Some functions might expect different response structures.

**Recommendation**: 
```python
# Use the actual tool result structure
tool_response = {}
if result.content:
    for content in result.content:
        if content.type == "text":
            tool_response["result"] = content.text
        elif content.type == "image":
            tool_response["image"] = content.data  # Handle images if needed
        # Add other content types as needed

response = chat.send_message(
    types.Part.from_function_response(
        name=call.name,
        response=tool_response  # Use actual response structure
    )
)
```

### 3. **Missing Error Handling for Tool Calls (Line 85)**
**Issue**: No error handling for MCP tool call failures.

**Problem**: If `session.call_tool()` fails (invalid arguments, tool not found, network issues), the exception will crash the loop.

**Recommendation**:
```python
try:
    result = await session.call_tool(call.name, call.args)
except Exception as tool_error:
    print(f"  > Tool error: {tool_error}")
    # Send error back to Gemini so it can handle it
    response = chat.send_message(
        types.Part.from_function_response(
            name=call.name,
            response={"error": str(tool_error)}
        )
    )
    continue
```

### 4. **Tool Call Arguments Format (Line 85)**
**Issue**: `call.args` might not be in the correct format for MCP.

**Problem**: Gemini's `FunctionCall.args` might be a dict, but MCP's `call_tool` expects `arguments` parameter. Need to verify the format.

**Recommendation**:
```python
# Ensure args is a dict
tool_args = dict(call.args) if call.args else {}
result = await session.call_tool(call.name, arguments=tool_args)
```

### 5. **Async/Sync Mixing (Line 77, 98)**
**Issue**: `chat.send_message()` might be synchronous, blocking the async event loop.

**Problem**: If `send_message()` is blocking, it will prevent other async operations and reduce performance.

**Recommendation**: Check if there's an async version or run in executor:
```python
# Option 1: Use async version if available
response = await chat.asend_message(user_input)  # If available

# Option 2: Run in executor to avoid blocking
import concurrent.futures
loop = asyncio.get_event_loop()
with concurrent.futures.ThreadPoolExecutor() as executor:
    response = await loop.run_in_executor(
        executor, 
        lambda: chat.send_message(user_input)
    )
```

## Important Issues

### 6. **Missing Tool Validation (Line 85)**
**Issue**: No validation that the tool exists in `tool_map` before calling.

**Recommendation**:
```python
if call.name not in tool_map:
    print(f"  > Warning: Tool '{call.name}' not found in tool map")
    response = chat.send_message(
        types.Part.from_function_response(
            name=call.name,
            response={"error": f"Tool '{call.name}' not available"}
        )
    )
    continue
```

### 7. **Incomplete Content Type Handling (Lines 90-93)**
**Issue**: Only handles text content, ignores other MCP content types.

**Problem**: MCP can return images, JSON, and other content types that should be passed to Gemini.

**Recommendation**:
```python
tool_output_parts = []
if result.content:
    for content in result.content:
        if content.type == "text":
            tool_output_parts.append({"text": content.text})
        elif content.type == "image":
            tool_output_parts.append({"image": content.data})
        elif content.type == "json":
            tool_output_parts.append({"json": content.json})
        # Handle other types as needed

# Use appropriate response format based on content
if len(tool_output_parts) == 1 and "text" in tool_output_parts[0]:
    response_data = {"result": tool_output_parts[0]["text"]}
else:
    response_data = {"content": tool_output_parts}
```

### 8. **No Timeout Handling**
**Issue**: No timeouts for MCP tool calls or Gemini API calls.

**Problem**: Long-running queries or network issues could hang indefinitely.

**Recommendation**:
```python
import asyncio

# Add timeout to tool calls
try:
    result = await asyncio.wait_for(
        session.call_tool(call.name, arguments=tool_args),
        timeout=300.0  # 5 minutes for BigQuery queries
    )
except asyncio.TimeoutError:
    print(f"  > Tool call timed out: {call.name}")
    response = chat.send_message(
        types.Part.from_function_response(
            name=call.name,
            response={"error": "Tool call timed out"}
        )
    )
    continue
```

### 9. **Missing Conversation History Management**
**Issue**: No explicit conversation history tracking.

**Problem**: While `chat.send_message()` should maintain history, there's no way to reset or inspect it.

**Recommendation**: Add conversation management:
```python
# Add conversation reset option
if user_input.lower() == "reset":
    chat = client.chats.create(
        model=MODEL_ID,
        config=types.GenerateContentConfig(
            tools=[types.Tool(function_declarations=gemini_tools)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
        )
    )
    print("Conversation reset.")
    continue
```

### 10. **Environment Variable Validation**
**Issue**: Only checks for `BIGQUERY_PROJECT`, but doesn't validate Vertex AI credentials.

**Recommendation**:
```python
if not PROJECT_ID:
    print("Error: BIGQUERY_PROJECT environment variable not set.")
    sys.exit(1)

# Validate Vertex AI credentials
try:
    from google.auth import default
    credentials, project = default()
    if not credentials:
        print("Error: No Google Cloud credentials found.")
        print("Please run: gcloud auth application-default login")
        sys.exit(1)
except Exception as e:
    print(f"Error: Failed to load credentials: {e}")
    sys.exit(1)
```

## Code Quality Improvements

### 11. **Type Hints**
**Issue**: Missing type hints for better code maintainability.

**Recommendation**: Add proper type hints:
```python
from typing import Dict, List, Optional, Any
from mcp.types import Tool, CallToolResult
from google.genai.types import FunctionCall, GenerateContentResponse

tool_map: Dict[str, Tool] = {}
```

### 12. **Logging Instead of Print**
**Issue**: Using `print()` statements instead of proper logging.

**Recommendation**:
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logger.info(f"Starting agent for project: {PROJECT_ID}")
logger.error(f"Error: {e}")
```

### 13. **Configuration Management**
**Issue**: Hardcoded configuration values.

**Recommendation**: Use environment variables or config file:
```python
MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-exp")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
TOOL_TIMEOUT = float(os.environ.get("TOOL_TIMEOUT", "300.0"))
```

### 14. **Graceful Shutdown**
**Issue**: No cleanup on exit.

**Recommendation**:
```python
try:
    while True:
        # ... main loop
except KeyboardInterrupt:
    print("\nShutting down gracefully...")
finally:
    # Cleanup if needed
    pass
```

## Security Considerations

### 15. **Input Sanitization**
**Issue**: User input is passed directly to Gemini without validation.

**Recommendation**: Add basic input validation:
```python
if not user_input.strip():
    continue

# Optional: Add length limits
if len(user_input) > 10000:
    print("Input too long. Please limit to 10,000 characters.")
    continue
```

### 16. **Tool Execution Security**
**Issue**: No validation of tool arguments before execution.

**Recommendation**: Validate tool arguments against schema:
```python
# Validate arguments against tool schema before calling
tool = tool_map[call.name]
# Add schema validation logic here
```

## Performance Optimizations

### 17. **Multiple Function Calls**
**Issue**: Processing function calls sequentially.

**Problem**: If Gemini requests multiple tool calls, they could potentially run in parallel.

**Recommendation**: Consider parallel execution for independent tool calls:
```python
# Collect all tool calls first
tool_calls = list(response.function_calls)

# Execute in parallel if independent
if len(tool_calls) > 1:
    tasks = [
        session.call_tool(call.name, arguments=dict(call.args))
        for call in tool_calls
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # Process results...
else:
    # Sequential execution for single calls
    ...
```

### 18. **Response Streaming**
**Issue**: No streaming support for long responses.

**Recommendation**: Consider implementing streaming for better UX:
```python
# If streaming is available
response = chat.send_message_stream(user_input)
for chunk in response:
    print(chunk.text, end='', flush=True)
```

## Testing Recommendations

1. **Unit Tests**: Test tool conversion, error handling, content extraction
2. **Integration Tests**: Test MCP connection, tool execution, Gemini API calls
3. **Error Scenarios**: Test timeout, invalid tools, network failures
4. **Edge Cases**: Empty responses, multiple function calls, large outputs

## Documentation Improvements

1. Add docstrings to functions
2. Document environment variables required
3. Add usage examples
4. Document error codes and recovery

## Summary

**Critical Issues**: 5
**Important Issues**: 5  
**Code Quality**: 4
**Security**: 2
**Performance**: 2

**Priority Actions**:
1. Fix tool schema conversion (Critical)
2. Add proper error handling (Critical)
3. Fix function response format (Critical)
4. Add timeout handling (Important)
5. Improve content type handling (Important)

