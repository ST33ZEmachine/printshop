"""
BigQuery Natural Language Agent

A conversational agent that enables natural language queries against BigQuery
using Google Gemini AI and Model Context Protocol (MCP) for tool integration.
"""

import asyncio
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import errors, types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool, CallToolResult

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from environment variables
PROJECT_ID = os.environ.get("BIGQUERY_PROJECT")
MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-exp")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
TOOL_TIMEOUT = float(os.environ.get("TOOL_TIMEOUT", "300.0"))  # 5 minutes default
MAX_INPUT_LENGTH = int(os.environ.get("MAX_INPUT_LENGTH", "10000"))
DATA_CONTEXT_FILE = os.environ.get("DATA_CONTEXT_FILE", "data_context.md")
MAX_TOOL_CALLS_PER_TURN = int(os.environ.get("MAX_TOOL_CALLS_PER_TURN", "12"))


def validate_credentials() -> None:
    """Validate Google Cloud credentials are available."""
    try:
        from google.auth import default
        credentials, project = default()
        if not credentials:
            logger.error("No Google Cloud credentials found.")
            logger.error("Please run: gcloud auth application-default login")
            sys.exit(1)
        logger.debug("Credentials validated successfully")
    except Exception as e:
        logger.error(f"Failed to load credentials: {e}")
        sys.exit(1)


def convert_mcp_schema_to_gemini(tool: Tool) -> Dict[str, Any]:
    """
    Convert MCP tool input schema to Gemini's expected format.
    
    Args:
        tool: MCP Tool object with inputSchema
        
    Returns:
        Dictionary suitable for Gemini's parameters_json_schema
    """
    if isinstance(tool.inputSchema, dict):
        return tool.inputSchema
    elif hasattr(tool.inputSchema, 'model_dump'):
        # Pydantic model
        return tool.inputSchema.model_dump()
    elif hasattr(tool.inputSchema, 'dict'):
        # Pydantic v1
        return tool.inputSchema.dict()
    else:
        # Try to convert to dict
        try:
            return dict(tool.inputSchema)
        except (TypeError, ValueError):
            logger.warning(f"Could not convert schema for tool {tool.name}, using empty dict")
            return {}


def extract_tool_response_content(result: CallToolResult) -> Dict[str, Any]:
    """
    Extract content from MCP tool result, handling multiple content types.
    
    Args:
        result: CallToolResult from MCP
        
    Returns:
        Dictionary with tool response data
    """
    tool_response: Dict[str, Any] = {}
    text_parts: List[str] = []
    other_content: List[Dict[str, Any]] = []
    
    if result.content:
        for content in result.content:
            if content.type == "text":
                text_parts.append(content.text)
            elif content.type == "image":
                other_content.append({
                    "type": "image",
                    "data": getattr(content, 'data', None) or getattr(content, 'image', None)
                })
            elif content.type == "json":
                other_content.append({
                    "type": "json",
                    "data": getattr(content, 'json', None) or getattr(content, 'data', None)
                })
            else:
                # Handle unknown content types
                logger.warning(f"Unknown content type: {content.type}")
                other_content.append({
                    "type": content.type,
                    "data": getattr(content, 'data', None)
                })
    
    # Prefer text result if available, otherwise use structured content
    if text_parts:
        if len(text_parts) == 1:
            tool_response["result"] = text_parts[0]
        else:
            tool_response["result"] = "\n".join(text_parts)
    elif other_content:
        tool_response["content"] = other_content
    else:
        tool_response["result"] = "Tool executed successfully (no output)"
    
    return tool_response


async def execute_tool_call(
    session: ClientSession,
    call: types.FunctionCall,
    tool_map: Dict[str, Tool],
    timeout: float
) -> CallToolResult:
    """
    Execute a single tool call via MCP with proper error handling.
    
    Args:
        session: MCP client session
        call: Gemini function call request
        tool_map: Map of tool names to Tool objects
        timeout: Timeout in seconds
        
    Returns:
        CallToolResult from MCP
        
    Raises:
        ValueError: If tool not found
        asyncio.TimeoutError: If tool call times out
        Exception: For other tool execution errors
    """
    # Validate tool exists
    if call.name not in tool_map:
        raise ValueError(f"Tool '{call.name}' not found in tool map")
    
    # Convert args to dict format expected by MCP
    tool_args = dict(call.args) if call.args else {}
    
    # Debug logging for SQL queries
    if call.name in {"execute_sql", "query"}:
        query_text = tool_args.get("query")
        if query_text:
            snippet = query_text.strip().replace("\n", " ")[:500]
            logger.debug(f"Executing SQL query (first 500 chars): {snippet}")
    
    # Execute with timeout
    try:
        result = await asyncio.wait_for(
            session.call_tool(call.name, arguments=tool_args),
            timeout=timeout
        )
        return result
    except asyncio.TimeoutError:
        logger.error(f"Tool call timed out: {call.name}")
        raise
    except Exception as e:
        logger.error(f"Tool call failed for {call.name}: {e}")
        raise


async def process_tool_calls(
    session: ClientSession,
    function_calls: List[types.FunctionCall],
    tool_map: Dict[str, Tool],
    chat: Any,  # Chat object from genai
    timeout: float
) -> Optional[Any]:
    """
    Process multiple tool calls, handling them sequentially.
    
    Args:
        session: MCP client session
        function_calls: List of function calls from Gemini
        tool_map: Map of tool names to Tool objects
        chat: Gemini chat session
        timeout: Timeout for each tool call
        
    Returns:
        Final response from Gemini after processing all tool calls
    """
    if not function_calls:
        return None
    
    # Process tool calls sequentially (BigQuery queries may depend on each other)
    # For independent calls, could be parallelized, but safer to do sequentially
    last_response = None
    
    for call in function_calls:
        logger.info(f"Calling tool: {call.name}")
        
        try:
            # Execute tool
            result = await execute_tool_call(session, call, tool_map, timeout)
            
            # Extract response content
            tool_response = extract_tool_response_content(result)
            
            logger.info(f"Tool output received ({len(str(tool_response))} chars)")
            
            # Send response back to Gemini
            # Use ThreadPoolExecutor to avoid blocking async event loop
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                last_response = await loop.run_in_executor(
                    executor,
                    lambda: chat.send_message(
                        types.Part.from_function_response(
                            name=call.name,
                            response=tool_response
                        )
                    )
                )
                
        except ValueError as e:
            # Tool not found
            logger.warning(f"Tool error: {e}")
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                last_response = await loop.run_in_executor(
                    executor,
                    lambda: chat.send_message(
                        types.Part.from_function_response(
                            name=call.name,
                            response={"error": str(e)}
                        )
                    )
                )
        except asyncio.TimeoutError:
            logger.error(f"Tool call timed out: {call.name}")
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                last_response = await loop.run_in_executor(
                    executor,
                    lambda: chat.send_message(
                        types.Part.from_function_response(
                            name=call.name,
                            response={"error": "Tool call timed out"}
                        )
                    )
                )
        except Exception as e:
            logger.error(f"Unexpected error executing tool {call.name}: {e}")
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                last_response = await loop.run_in_executor(
                    executor,
                    lambda: chat.send_message(
                        types.Part.from_function_response(
                            name=call.name,
                            response={"error": f"Tool execution failed: {str(e)}"}
                        )
                    )
                )
    
    return last_response


def validate_user_input(user_input: str) -> bool:
    """
    Validate user input before processing.
    
    Args:
        user_input: User's input string
        
    Returns:
        True if input is valid, False otherwise
    """
    if not user_input.strip():
        return False
    
    if len(user_input) > MAX_INPUT_LENGTH:
        logger.warning(f"Input too long ({len(user_input)} chars, max {MAX_INPUT_LENGTH})")
        return False
    
    return True


def load_data_context() -> Optional[str]:
    """
    Load data context from file if it exists.
    
    Returns:
        Data context string if file exists, None otherwise
    """
    if os.path.exists(DATA_CONTEXT_FILE):
        try:
            with open(DATA_CONTEXT_FILE, 'r') as f:
                content = f.read()
                logger.info(f"Loaded data context from {DATA_CONTEXT_FILE}")
                return content
        except Exception as e:
            logger.warning(f"Could not load data context from {DATA_CONTEXT_FILE}: {e}")
    return None


async def discover_schema(
    session: ClientSession,
    tool_map: Dict[str, Tool],
    timeout: float = 30.0
) -> str:
    """
    Discover BigQuery schema information to provide context to the agent.
    
    Args:
        session: MCP client session
        tool_map: Map of tool names to Tool objects
        timeout: Timeout for schema discovery operations
        
    Returns:
        String containing schema information
    """
    schema_info = []
    
    # Try to discover datasets and tables
    # Common BigQuery MCP tool names for schema discovery
    discovery_tools = [
        'list_datasets',
        'list_tables',
        'get_table_schema',
        'query',  # Some MCP servers might have a query tool we can use for schema discovery
    ]
    
    for tool_name in discovery_tools:
        if tool_name in tool_map:
            try:
                logger.info(f"Attempting schema discovery using {tool_name}")
                
                # Different tools may need different arguments
                if tool_name == 'list_datasets':
                    args = {}
                elif tool_name == 'list_tables':
                    # Try to list tables - may need dataset parameter
                    args = {}
                elif tool_name == 'get_table_schema':
                    # Would need table name, skip for now
                    continue
                elif tool_name == 'query':
                    # Try a simple schema discovery query
                    args = {
                        'query': 'SELECT table_schema, table_name FROM `INFORMATION_SCHEMA.TABLES` LIMIT 20'
                    }
                else:
                    args = {}
                
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments=args),
                    timeout=timeout
                )
                if result.content:
                    for content in result.content:
                        if content.type == "text":
                            schema_info.append(f"=== {tool_name} ===\n{content.text}")
                            break  # Only take first text content
            except asyncio.TimeoutError:
                logger.debug(f"Schema discovery tool {tool_name} timed out")
            except Exception as e:
                logger.debug(f"Could not use {tool_name} for schema discovery: {e}")
    
    if schema_info:
        return "\n\n".join(schema_info)
    else:
        return "Schema discovery attempted but no information available. Use tools directly to explore data."


def create_system_instruction(project_id: str) -> str:
    """
    Create system instruction for the agent with Trello order context.
    
    Args:
        project_id: BigQuery project ID
        
    Returns:
        System instruction string
    """
    return f"""You are a helpful BigQuery data analyst assistant for project {project_id}.

IMPORTANT CONTEXT:
- The data you are accessing comes from a Trello board that tracks orders made to the business
- You are working with order information, customer details, and order statuses
- The data structure reflects how orders are organized in Trello (cards, lists, labels, etc.)

CRITICAL SEARCH GUIDELINES - READ CAREFULLY:
When searching for text in BigQuery, you MUST follow these rules:

1. ALWAYS use LOWER() or UPPER() for case-insensitive text searches
   - BigQuery LIKE is case-sensitive by default
   - Example: LOWER(column_name) LIKE '%search_term%'

2. For multi-word search terms, break them into individual words
   - Don't search for exact phrases like '%team Canada rugby%'
   - Instead, search for individual words with AND/OR logic
   - Example: For "team Canada rugby", use:
     LOWER(name) LIKE '%canada%' AND LOWER(name) LIKE '%rugby%'
     OR LOWER(desc) LIKE '%canada%' AND LOWER(desc) LIKE '%rugby%'

3. Search across multiple columns with OR conditions
   - Always search name, desc (or description), and labels columns
   - Use OR to combine searches across columns

4. Use wildcards (%) on both sides for partial matching
   - Pattern: LOWER(column) LIKE '%word%'

5. Example query pattern for searching "team Canada rugby":
   SELECT * FROM table_name
   WHERE (LOWER(name) LIKE '%canada%' AND LOWER(name) LIKE '%rugby%')
      OR (LOWER(desc) LIKE '%canada%' AND LOWER(desc) LIKE '%rugby%')
      OR (LOWER(labels) LIKE '%canada%' AND LOWER(labels) LIKE '%rugby%')

6. RESERVED WORDS / SPECIAL COLUMNS:
   - Some columns, like desc, are reserved words in SQL
   - ALWAYS wrap reserved column names in backticks, e.g. `desc`
   - If a column name contains spaces or special characters, wrap it in backticks
   - When using LOWER() with backticks, use LOWER(`desc`)

7. ERROR HANDLING:
   - If BigQuery reports a syntax or invalid field error, stop and inspect the query
   - Do not immediately retry the same failing query; adjust the SQL to fix the issue
   - Explain to the user what went wrong before issuing another query

Your role:
- Help users query and understand their Trello-based order data in BigQuery
- Always use the available tools to explore schemas before making assumptions
- When users ask about orders, first discover what tables and datasets exist
- Understand that data may be organized in ways that reflect Trello's structure (cards, lists, members, etc.)
- Explain your queries and results clearly in the context of business orders
- If you're unsure about table structures, use schema discovery tools first

Best practices:
- Start by listing available datasets and tables when exploring new data
- Check table schemas before writing queries
- Use appropriate SQL patterns for BigQuery
- Handle errors gracefully and suggest alternatives
- Remember that you're working with order data from Trello
- ALWAYS use case-insensitive searches with LOWER() function
- Break down multi-word searches into individual word searches

When users ask about:
- Orders: Look for tables containing order information, order IDs, dates, statuses
- Customers: Look for customer/client information associated with orders
- Status: Look for order status fields (may reflect Trello list names or labels)
- Dates: Pay attention to order dates, due dates, and completion dates
- Amounts/Pricing: Look for order value, pricing, or cost information

Always verify table and column names exist before using them in queries."""


async def main() -> None:
    """Main agent loop."""
    # Validate environment
    if not PROJECT_ID:
        logger.error("BIGQUERY_PROJECT environment variable not set.")
        sys.exit(1)
    
    # Validate credentials
    validate_credentials()
    
    logger.info(f"Starting agent for project: {PROJECT_ID}")
    logger.info(f"Using model: {MODEL_ID}")
    
    # MCP Server Parameters
    server_params = StdioServerParameters(
        command="./toolbox",
        args=["--prebuilt", "bigquery", "--stdio", "--port", "0"],
        env={**os.environ, "BIGQUERY_PROJECT": PROJECT_ID}
    )
    
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                # List tools from MCP
                mcp_tools = await session.list_tools()
                logger.info(f"Connected to MCP. Found {len(mcp_tools.tools)} tools.")
                
                # Convert MCP tools to Gemini tools
                gemini_tools: List[types.FunctionDeclaration] = []
                tool_map: Dict[str, Tool] = {}
                
                for tool in mcp_tools.tools:
                    tool_map[tool.name] = tool
                    
                    # Convert MCP schema to Gemini format
                    parameters = convert_mcp_schema_to_gemini(tool)
                    
                    func_decl = types.FunctionDeclaration(
                        name=tool.name,
                        description=tool.description or f"Tool: {tool.name}",
                        parameters_json_schema=parameters
                    )
                    gemini_tools.append(func_decl)
                
                logger.info(f"Converted {len(gemini_tools)} tools for Gemini")
                
                # Initialize Gemini Client
                client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
                
                # Create system instruction with Trello order context
                system_instruction = create_system_instruction(PROJECT_ID)
                
                # Create chat session with system instructions
                chat = client.chats.create(
                    model=MODEL_ID,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        tools=[types.Tool(function_declarations=gemini_tools)],
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                    )
                )
                
                # Load and inject data context if available
                data_context = load_data_context()
                if data_context:
                    logger.info("Injecting data context into conversation")
                    loop = asyncio.get_event_loop()
                    with ThreadPoolExecutor() as executor:
                        await loop.run_in_executor(
                            executor,
                            lambda: chat.send_message(
                                f"Here is important context about the Trello order data:\n\n{data_context}\n\n"
                                "Please use this information to better understand user queries about orders."
                            )
                        )
                
                # Discover schema and inject as initial context
                logger.info("Discovering BigQuery schema...")
                schema_context = await discover_schema(session, tool_map)
                if schema_context and "no information available" not in schema_context.lower():
                    logger.info("Injecting schema context into conversation")
                    loop = asyncio.get_event_loop()
                    with ThreadPoolExecutor() as executor:
                        await loop.run_in_executor(
                            executor,
                            lambda: chat.send_message(
                                f"Here is the current BigQuery schema information:\n\n{schema_context}\n\n"
                                "Please remember this context for future queries about the Trello order data."
                            )
                        )
                
                logger.info("Agent ready. Type 'exit' or 'quit' to quit, 'reset' to reset conversation, 'describe data' or 'schema' to refresh schema.")
                print("\nAgent ready. Type 'exit' or 'quit' to quit, 'reset' to reset conversation, 'describe data' or 'schema' to refresh schema.")
                
                # Main conversation loop
                while True:
                    try:
                        user_input = input("\nYou: ")
                        
                        # Handle special commands
                        if user_input.lower() in ["exit", "quit"]:
                            logger.info("User requested exit")
                            break
                        
                        if user_input.lower() == "reset":
                            logger.info("Resetting conversation")
                            system_instruction = create_system_instruction(PROJECT_ID)
                            chat = client.chats.create(
                                model=MODEL_ID,
                                config=types.GenerateContentConfig(
                                    system_instruction=system_instruction,
                                    tools=[types.Tool(function_declarations=gemini_tools)],
                                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)
                                )
                            )
                            # Re-inject context after reset
                            data_context = load_data_context()
                            if data_context:
                                loop = asyncio.get_event_loop()
                                with ThreadPoolExecutor() as executor:
                                    await loop.run_in_executor(
                                        executor,
                                        lambda: chat.send_message(
                                            f"Here is important context about the Trello order data:\n\n{data_context}\n\n"
                                            "Please use this information to better understand user queries about orders."
                                        )
                                    )
                            print("Conversation reset.")
                            continue
                        
                        if user_input.lower() in ["describe data", "schema"]:
                            logger.info("User requested schema refresh")
                            schema_context = await discover_schema(session, tool_map)
                            if schema_context:
                                print(f"\n=== Current Schema ===\n{schema_context}\n")
                                # Also send to chat for context
                                loop = asyncio.get_event_loop()
                                with ThreadPoolExecutor() as executor:
                                    await loop.run_in_executor(
                                        executor,
                                        lambda: chat.send_message(
                                            f"User requested schema refresh. Here's the current schema:\n\n{schema_context}"
                                        )
                                    )
                            else:
                                print("Schema discovery not available. Try using the list_datasets or list_tables tools directly.")
                            continue
                        
                        # Validate input
                        if not validate_user_input(user_input):
                            if len(user_input) > MAX_INPUT_LENGTH:
                                print(f"Input too long. Please limit to {MAX_INPUT_LENGTH} characters.")
                            continue
                        
                        # Send message to Gemini (run in executor to avoid blocking)
                        loop = asyncio.get_event_loop()
                        with ThreadPoolExecutor() as executor:
                            response = await loop.run_in_executor(
                                executor,
                                lambda: chat.send_message(user_input)
                            )
                        
                        # Handle tool calls with guard against infinite loops
                        tool_calls_executed = 0
                        while response.function_calls:
                            current_calls = list(response.function_calls)
                            tool_calls_executed += len(current_calls)
                            
                            if tool_calls_executed > MAX_TOOL_CALLS_PER_TURN:
                                warning_msg = (
                                    "Tool call limit reached for this request. "
                                    "Unable to complete the query without exceeding safety limits."
                                )
                                logger.warning(warning_msg)
                                print(warning_msg)
                                break
                            
                            # Process current batch of tool calls
                            tool_response = await process_tool_calls(
                                session,
                                current_calls,
                                tool_map,
                                chat,
                                TOOL_TIMEOUT
                            )
                            
                            if tool_response:
                                response = tool_response
                            else:
                                # No more function calls
                                break
                        
                        # Print final response
                        if response.text:
                            print(f"Agent: {response.text}")
                        elif response.function_calls:
                            logger.warning("Response has function calls but no text")
                        else:
                            logger.warning("Empty response from Gemini")
                            
                    except (EOFError, KeyboardInterrupt):
                        # EOFError occurs when stdin is closed (non-interactive terminal)
                        # KeyboardInterrupt occurs when user presses Ctrl+C
                        logger.info("Exiting due to EOF or interrupt")
                        print("\nExiting...")
                        break
                    except errors.APIError as e:
                        logger.error(f"Gemini API error: {e.code} - {e.message}")
                        print(f"Error: API error {e.code}: {e.message}")
                    except Exception as e:
                        logger.exception("Unexpected error in main loop")
                        print(f"Error: {e}")
                        
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
        print("\nShutting down gracefully...")
    except Exception as e:
        logger.exception("Fatal error")
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
