# Agent Data Understanding Improvements

## Summary
Enhanced the agent to better understand Trello order data through system instructions, schema discovery, and data context loading.

## Implemented Features

### 1. System Instructions ✅
- **Location**: `create_system_instruction()` function
- **Purpose**: Provides the agent with context about:
  - Working with Trello order data
  - Understanding Trello data structure (cards, lists, labels, members)
  - Best practices for querying order information
  - Common patterns for finding orders, statuses, customers, and amounts
- **Impact**: Agent now understands it's working with order data from Trello

### 2. Data Context File ✅
- **File**: `data_context.md`
- **Purpose**: Documents the structure and patterns of Trello order data
- **Contents**:
  - Overview of Trello data structure
  - Key concepts (cards, lists, labels, members)
  - Common data patterns
  - Querying tips
  - Example query patterns
- **Usage**: Automatically loaded on startup and after reset

### 3. Schema Discovery ✅
- **Function**: `discover_schema()`
- **Purpose**: Automatically discovers BigQuery schema on startup
- **Features**:
  - Tries multiple discovery tools (list_datasets, list_tables, query)
  - Handles timeouts gracefully
  - Provides schema information to the agent
- **Impact**: Agent knows what tables and datasets are available

### 4. Context Injection ✅
- **On Startup**: 
  - Loads data context from `data_context.md`
  - Discovers schema automatically
  - Injects both into the conversation
- **After Reset**: Re-injects data context
- **Impact**: Agent has full context from the start

### 5. Describe Data Command ✅
- **Commands**: `describe data` or `schema`
- **Purpose**: Allows users to refresh schema understanding
- **Features**:
  - Discovers current schema
  - Displays to user
  - Injects into conversation for agent context
- **Usage**: Type `describe data` or `schema` at any time

## Files Modified

### `agent.py`
- Added `DATA_CONTEXT_FILE` environment variable
- Added `load_data_context()` function
- Added `discover_schema()` function
- Added `create_system_instruction()` function
- Modified chat creation to include system instructions
- Added context injection on startup
- Added "describe data" command handler
- Enhanced reset command to re-inject context

### `data_context.md` (New)
- Comprehensive documentation of Trello order data structure
- Query patterns and tips
- Common data field explanations

## Environment Variables

- `DATA_CONTEXT_FILE` (optional, default: `data_context.md`) - Path to data context file

## Usage

### Normal Operation
The agent now automatically:
1. Loads system instructions about Trello orders
2. Loads data context from `data_context.md`
3. Discovers schema on startup
4. Injects all context into the conversation

### Commands
- `describe data` or `schema` - Refresh schema understanding
- `reset` - Reset conversation (re-injects context)
- `exit` or `quit` - Exit agent

## Benefits

1. **Better Understanding**: Agent knows it's working with Trello order data
2. **Faster Queries**: Schema discovery means agent knows available tables
3. **Accurate Results**: Context about data structure improves query accuracy
4. **User Control**: Users can refresh schema understanding anytime
5. **Maintainable**: Data context can be updated in `data_context.md`

## Customization

### Update Data Context
Edit `data_context.md` to:
- Add specific table names
- Document custom fields
- Add business rules
- Include example queries

### Customize System Instructions
Modify `create_system_instruction()` to:
- Add domain-specific knowledge
- Include business rules
- Add query patterns
- Customize behavior

## Next Steps

Consider:
1. Updating `data_context.md` with your actual table names and structure
2. Adding specific business rules to the system instructions
3. Customizing schema discovery based on your actual BigQuery setup
4. Adding more example queries to the data context

