# LangChain RAG System with PostgreSQL and FastAPI

This project implements a Retrieval-Augmented Generation (RAG) system that connects to a PostgreSQL database, extracts its schema (including tables, views, and comments), and allows users to query the database using natural language. The system is built with LangChain, FastAPI, and Docker Compose.

## Architecture Overview

The system consists of the following components orchestrated by Docker Compose:

1.  **FastAPI Application (`app`)**:
    *   Serves a REST API for natural language queries.
    *   Extracts metadata (schema, comments) from the PostgreSQL database on startup using `metadata_extractor.py`.
    *   Embeds this metadata and stores it in a ChromaDB vector store.
    *   Uses LangChain's `RetrievalQA` chain to fetch relevant schema context based on the user's query.
    *   Uses LangChain's SQL Agent (`create_sql_agent`) to generate and execute SQL queries against the PostgreSQL database, informed by the retrieved context.
2.  **PostgreSQL Database (`db`)**:
    *   The source SQL database that the RAG system will interact with.
    *   Stores the actual data and schema.
3.  **ChromaDB (`chroma`)**:
    *   A vector database used to store embeddings of the PostgreSQL schema metadata.
    *   Provides fast semantic search capabilities for retrieving relevant schema parts.

## Prerequisites

*   Docker and Docker Compose installed.
*   An OpenAI API Key (the application currently uses OpenAI for embeddings and the LLM).

## Project Structure

```
.
├── Dockerfile           # Dockerfile for the FastAPI application
├── docker-compose.yml   # Docker Compose configuration for all services
├── main.py              # FastAPI application logic, RAG pipeline
├── metadata_extractor.py # Script to extract schema from PostgreSQL
├── requirements.txt     # Python dependencies
├── README.md            # This file
└── .env.example         # Example environment file (create your own .env)
```

## Setup and Running

1.  **Clone the Repository (if applicable)**
    ```bash
    # git clone <repository-url>
    # cd <repository-name>
    ```

2.  **Create a `.env` File**:
    Copy the `.env.example` (or create a new `.env` file) in the project root and fill in your details:
    ```env
    # .env
    POSTGRES_USER=myuser
    POSTGRES_PASSWORD=mypassword
    POSTGRES_DB=ragdb

    # Your OpenAI API Key is required for embeddings and the LLM
    OPENAI_API_KEY="sk-your_openai_api_key_here"

    # These are defaults used by docker-compose.yml and main.py,
    # you typically don't need to change them unless you modify docker-compose.yml
    # DB_HOST=db # Service name in Docker network
    # DB_PORT=5432
    # CHROMA_HOST=chroma # Service name in Docker network
    # CHROMA_PORT=8000 # Internal Chroma service port
    ```
    **Important**: The `OPENAI_API_KEY` is crucial for the application to work. I'll also create an `.env.example` file.

3.  **Build and Run with Docker Compose**:
    Open your terminal in the project root directory and run:
    ```bash
    docker-compose up --build
    ```
    This command will:
    *   Build the Docker image for the FastAPI application.
    *   Pull the official PostgreSQL and ChromaDB images.
    *   Start all three services (`app`, `db`, `chroma`).

    You should see logs from all services. The `app` service will log its initialization steps, including connecting to the database, extracting schema, and setting up LangChain components. Wait for messages indicating that the application has started successfully (e.g., `Uvicorn running on http://0.0.0.0:8000`).

4.  **Initial Database Schema (Optional but Recommended)**:
    The RAG system works best if your PostgreSQL database (`ragdb` by default) already has some tables, views, and ideally, comments on them.
    *   You can connect to the PostgreSQL instance (e.g., using `psql` or a GUI tool like DBeaver/pgAdmin) on `localhost:5432` with the credentials from your `.env` file.
    *   Create your schema. Example DDL is provided in `metadata_extractor.py` comments for testing.

    If the database is empty when the `app` service starts, `metadata_extractor.py` will extract no schema information, and the vector store will contain minimal context. The application attempts to handle this gracefully but will be less effective.

## Usage

Once the services are running:

### 1. Health Check

You can check the health and status of the application components by navigating to:
`http://localhost:8000/health` in your browser or using `curl`:
```bash
curl http://localhost:8000/health
```
This will return a JSON response indicating the status of different components like LLM initialization, DB connection, Chroma connection, etc.

### 2. Querying the RAG System

Send a POST request to the `/query` endpoint with a JSON payload containing your natural language query.

**Example using `curl`**:
```bash
curl -X POST "http://localhost:8000/query" \
     -H "Content-Type: application/json" \
     -d '{
           "natural_language_query": "Show me all active contracts that have not been invoiced yet."
         }'
```

**Expected Response Structure**:
The API will return a JSON response like this:
```json
{
  "natural_language_query": "Show me all active contracts that have not been invoiced yet.",
  "sql_query": "SELECT T1.contract_id, T1.contract_name FROM sales.contracts AS T1 LEFT JOIN public.invoices AS T2 ON T1.contract_id = T2.contract_id WHERE T1.status = 'Active' AND T2.invoice_id IS NULL", // Example SQL
  "result": "[{\"contract_id\": 1, \"contract_name\": \"Contract Alpha\"}]", // Example result
  "context_from_vector_db": "Table: sales.contracts (Schema: sales)\nComment: Stores information about sales contracts.\nColumns:\n  - contract_id (integer): Unique identifier for the contract.\n  - contract_name (text)\n  - status (character varying): Current status of the contract (e.g., Draft, Signed, Active, Expired).\n  - signed_date (date)\n---\nTable: public.invoices (Schema: public)\nComment: Stores invoice data related to contracts.\nColumns:\n  - invoice_id (integer)\n  - contract_id (integer)\n  - invoice_date (date)\n  - amount (numeric): The total amount of the invoice.", // Example context
  "error": null
}
```

*   `natural_language_query`: Your original query.
*   `sql_query`: The SQL query generated by the LangChain SQL Agent (best-effort extraction).
*   `result`: The result obtained by executing the SQL query against the database. This is often a string representation of a list of dictionaries.
*   `context_from_vector_db`: The schema information retrieved from ChromaDB that was used as context for the SQL agent.
*   `error`: Any error message if the process failed.

## Development Notes

*   **Live Reload**: The `docker-compose.yml` for the `app` service mounts the current directory into the container. If you modify Python code, you'll need to restart the `app` service for changes to take effect, as the `CMD` in the `Dockerfile` does not use `--reload` for production stability. For development with live reload, you can modify the `command` for the `app` service in `docker-compose.yml` to `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`.
*   **Environment Variables**:
    *   `DATABASE_URL` for the app is constructed by `docker-compose.yml`.
    *   `CHROMA_HOST` and `CHROMA_PORT` point to the Chroma service within the Docker network.
*   **Schema Updates**: Currently, schema metadata is loaded into ChromaDB when the `app` service starts. If you change your PostgreSQL schema significantly, you should restart the `app` service to pick up the changes:
    ```bash
    docker-compose restart app
    ```
    A more advanced system might include periodic schema refresh or a webhook to trigger updates.
*   **LangChain Components**: The core LangChain setup is in `main.py`. Key components include:
    *   `ChatOpenAI` for the LLM.
    *   `OpenAIEmbeddings` for creating text embeddings.
    *   `Chroma` as the vector store client.
    *   `SQLDatabase` to interface with PostgreSQL.
    *   `RetrievalQA` chain for context retrieval.
    *   `create_sql_agent` for SQL generation and execution.

## Stopping the Application

To stop all services and remove the containers:
```bash
docker-compose down
```
To stop and remove volumes (PostgreSQL data, ChromaDB data):
```bash
docker-compose down -v
```

## Troubleshooting

*   **`OPENAI_API_KEY` not set**: Ensure your `.env` file is correct and contains your valid OpenAI API key. The application will fail to start critical components without it.
*   **Database Connection Issues**:
    *   Check that PostgreSQL (`db` service) is running and healthy (`docker-compose ps`).
    *   Verify credentials in `.env` match those used by the `db` service.
    *   Ensure the `DB_HOST` (which is `db` by default for the app service) is correct if you've customized network settings.
*   **ChromaDB Connection Issues**:
    *   Check that ChromaDB (`chroma` service) is running (`docker-compose ps`).
    *   Ensure `CHROMA_HOST` (`chroma`) and `CHROMA_PORT` (`8000` internal, mapped to `8001` on host) are correctly configured if defaults were changed.
*   **"No schema documents extracted"**: This warning means `metadata_extractor.py` couldn't find any tables/views in your database (or relevant schemas). Make sure your database has the necessary schema elements and the user configured has permissions to see them.
*   **Slow Startup**: Embedding schema documents on first startup can take a moment, especially if the schema is large. Check `app` service logs.
*   **Permissions**: The user connecting to PostgreSQL must have permissions to read `information_schema`, `pg_catalog.pg_description`, etc. The default `postgres` user usually has these.

This README provides a comprehensive guide to setting up, running, and using the RAG system.
