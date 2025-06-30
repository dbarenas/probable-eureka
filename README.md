# Natural Language to SQL RAG System

## Overview

This project implements a Retrieval Augmented Generation (RAG) system that allows users to query a PostgreSQL database using natural language. It leverages Large Language Models (LLMs) from OpenAI, the LangChain framework, a ChromaDB vector store for schema embeddings, and a FastAPI backend, all containerized with Docker.

The system works in two main phases:

1.  **Schema Ingestion (on application startup):**
    *   The application connects to the specified PostgreSQL database.
    *   It extracts detailed schema information, including table names, column names, data types, primary/foreign keys, and any available comments or descriptions for tables and columns, as well as view definitions.
    *   This schema information is then converted into vector embeddings using an OpenAI embedding model.
    *   These embeddings are stored in a ChromaDB vector database, creating a searchable knowledge base of the database schema.

2.  **Query Processing (on user request):**
    *   The user submits a natural language query (e.g., "Show me all customers from London" or "What is the total revenue for last month?").
    *   The system embeds the user's query and uses it to search the ChromaDB vector store for relevant schema information (table names, column names, descriptions) that might be needed to answer the query.
    *   The original natural language query, along with the retrieved schema context, is passed to a LangChain SQL Agent powered by an OpenAI LLM (e.g., GPT-3.5-turbo or GPT-4).
    *   The SQL Agent uses this combined information to generate an appropriate SQL query.
    *   The generated SQL query is executed against the PostgreSQL database.
    *   The results of the SQL query are returned to the user, effectively answering their natural language question.

This approach allows the LLM to have "awareness" of the database structure, leading to more accurate SQL generation, especially for complex databases or queries.

## System Architecture / Flow

```mermaid
graph LR
    subgraph User Interaction
        User[<fa:fa-user> User] -- Natural Language Query --> FastAPI
    end

    subgraph "Application Service (app)"
        FastAPI[<fa:fa-server> FastAPI Backend]
        FastAPI -- Embed & Search --> ChromaDB
        FastAPI -- Query + Context --> SQLAgent
        SQLAgent[<fa:fa-robot> LangChain SQL Agent (LLM)] -- Generate SQL --> SQLAgent
        SQLAgent -- Execute SQL --> PostgreSQL
    end

    subgraph "Vector Store (chroma)"
        ChromaDB[<fa:fa-database> ChromaDB Vector Store]
        FastAPI -- Store Schema Embeddings (on startup) --> ChromaDB
    end

    subgraph "Data Store (db)"
        PostgreSQL[<fa:fa-database> PostgreSQL Database]
    end

    subgraph External Services
        OpenAI[<fa:fa-cloud> OpenAI API]
        FastAPI -- Schema for Embedding --> OpenAI
        SQLAgent -- LLM for SQL Gen --> OpenAI
    end

    %% Data Flows for Querying
    User -- "1. Natural Language Query" --> FastAPI
    FastAPI -- "2. Embed Query & Retrieve Relevant Schema" --> ChromaDB
    ChromaDB -- "3. Relevant Schema Snippets" --> FastAPI
    FastAPI -- "4. Query + Schema Context" --> SQLAgent
    SQLAgent -- "5. Generate SQL (uses OpenAI)" --> SQLAgent
    SQLAgent -- "6. Execute SQL" --> PostgreSQL
    PostgreSQL -- "7. SQL Result" --> SQLAgent
    SQLAgent -- "8. Formatted Answer" --> FastAPI
    FastAPI -- "9. Final Response" --> User

    %% Data Flow for Schema Ingestion (Startup)
    FastAPI -- "A. Extract Schema" --> PostgreSQL
    PostgreSQL -- "B. Schema Details" --> FastAPI
    FastAPI -- "C. Embed Schema (uses OpenAI)" --> FastAPI
    FastAPI -- "D. Store Schema Embeddings" --> ChromaDB

    %% Service Dependencies
    FastAPI -.-> OpenAI
    SQLAgent -.-> OpenAI
```

**Breakdown of Components:**

*   **User:** Initiates a query in natural language.
*   **FastAPI Backend (`app` service):**
    *   Receives the user's query.
    *   Orchestrates the RAG pipeline using LangChain.
    *   Handles schema extraction and embedding storage during startup.
    *   Communicates with ChromaDB, PostgreSQL, and OpenAI.
*   **ChromaDB (`chroma` service):**
    *   Stores vector embeddings of the PostgreSQL database schema.
    *   Allows for efficient similarity search to find relevant schema parts based on the user's query.
*   **PostgreSQL Database (`db` service):**
    *   The target database containing the actual data and schema that the user wants to query.
*   **LangChain SQL Agent (within `app` service):**
    *   A specialized agent that uses an LLM (from OpenAI) and the retrieved schema context to generate and execute SQL queries.
*   **OpenAI API (External):**
    *   Provides the embedding models (to convert text to vectors) and the powerful LLMs (for understanding natural language and generating SQL).

## Features

*   **Natural Language Querying:** Interact with your SQL database using plain English.
*   **Retrieval Augmented Generation (RAG):** Enhances LLM accuracy by providing relevant database schema context.
*   **OpenAI Integration:** Utilizes OpenAI's state-of-the-art embedding and language models.
*   **PostgreSQL Backend:** Designed to work with PostgreSQL databases.
*   **ChromaDB Vector Store:** Efficiently stores and retrieves schema embeddings.
*   **Dockerized:** Easy setup and deployment using Docker and Docker Compose.
*   **FastAPI:** High-performance Python web framework for the backend API.
*   **LangChain:** Comprehensive framework for developing LLM-powered applications.
*   **Automatic Schema Ingestion:** Extracts and embeds database schema on startup.
*   **Health Check Endpoint:** Provides status of internal components.

## Prerequisites

*   **Docker:** Ensure Docker is installed and running on your system. ([Install Docker](https://docs.docker.com/get-docker/))
*   **Docker Compose:** Ensure Docker Compose (usually included with Docker Desktop) is installed. ([Install Docker Compose](https://docs.docker.com/compose/install/))
*   **OpenAI API Key:** You will need an active OpenAI API key with credits. You can get one from [platform.openai.com](https://platform.openai.com/).
*   **(Optional) `psql` or other PostgreSQL client:** Useful for directly interacting with the PostgreSQL database for setup, inspection, or debugging.

## Setup and Deployment

1.  **Clone the Repository (if you haven't already):**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Configure Environment Variables:**
    *   Copy the example environment file:
        ```bash
        cp .env.example .env
        ```
    *   Edit the `.env` file with your specific configurations:
        ```
        # .env

        # PostgreSQL Connection Details for docker-compose
        POSTGRES_USER=your_db_user        # Replace with your desired PostgreSQL username
        POSTGRES_PASSWORD=your_db_password  # Replace with your desired PostgreSQL password
        POSTGRES_DB=your_db_name          # Replace with your desired PostgreSQL database name

        # OpenAI API Key
        OPENAI_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" # Replace with your actual OpenAI API key

        # Optional: Default is PYTHONUNBUFFERED=1 for better logging in Docker
        PYTHONUNBUFFERED=1
        ```
        **Important:** The `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` variables in the `.env` file are used by `docker-compose.yml` to initialize the `db` service and also by the `app` service to connect to it. The `app` service uses `DB_HOST=db` (the service name) internally, as defined in `docker-compose.yml`.

3.  **Build and Run with Docker Compose:**
    *   Open your terminal in the project's root directory (where `docker-compose.yml` is located).
    *   Run the following command:
        ```bash
        docker-compose up --build -d
        ```
        *   `--build`: Forces Docker to rebuild the images if there are changes (e.g., in `Dockerfile` or source code).
        *   `-d`: Runs the containers in detached mode (in the background).

4.  **Initial Schema Ingestion:**
    *   On the first startup, the `app` service will connect to the `db` service, extract its schema (if any tables/views exist), embed this schema, and store it in the `chroma` service. This process might take a few moments depending on the size of your database schema and network speed for OpenAI API calls.
    *   You can monitor the logs of the application service to see this process:
        ```bash
        docker-compose logs -f app
        ```
        Look for messages indicating initialization of RAG components, schema loading, and connection to ChromaDB.

5.  **(Optional) Initialize Database with Schema/Data:**
    *   If your PostgreSQL database (`db` service) is starting empty, the RAG system won't have any specific schema to learn about. You need to populate it with tables, views, and data.
    *   **Method 1: Using an `init.sql` script (Recommended for initial setup):**
        1.  Create an SQL script (e.g., `init.sql`) in the root of your project directory with `CREATE TABLE`, `INSERT INTO`, `CREATE VIEW` statements, etc.
        2.  Uncomment the volume mount for `init.sql` in `docker-compose.yml`:
            ```yaml
            services:
              db:
                # ... other db config ...
                volumes:
                  - postgres_data:/var/lib/postgresql/data/
                  - ./init.sql:/docker-entrypoint-initdb.d/init.sql # <--- UNCOMMENT THIS
            ```
        3.  When you run `docker-compose up` (especially for the first time or after `docker-compose down -v`), this script will be executed by the PostgreSQL container, setting up your database.
    *   **Method 2: Connecting Manually:**
        *   After the `db` service is running, you can connect to it using a PostgreSQL client like `psql`:
            ```bash
            psql -h localhost -p 5432 -U your_db_user -d your_db_name
            ```
            (Use the `POSTGRES_USER` and `POSTGRES_DB` you set in your `.env` file. The password will be prompted.)
        *   Then, you can run your SQL commands to create schema and insert data.

    *   **Important:** After adding or significantly changing the database schema, you should restart the `app` service so it can re-extract and re-embed the schema:
        ```bash
        docker-compose restart app
        ```

## Usage

Once the services are up and running, and the schema has been ingested:

### 1. Querying the API

You can send natural language queries to the `/query` endpoint of the FastAPI application (which is mapped to port 8000 on your host by default).

**Request Format:**

*   **Method:** `POST`
*   **URL:** `http://localhost:8000/query`
*   **Body (JSON):**
    ```json
    {
      "natural_language_query": "Your natural language question about the data"
    }
    ```

**Example using `curl`:**

```bash
curl -X POST "http://localhost:8000/query" \
     -H "Content-Type: application/json" \
     -d '{
           "natural_language_query": "How many users signed up last month?"
         }'
```

**Example Response (Structure):**

The response will be a JSON object containing:

```json
{
  "natural_language_query": "How many users signed up last month?",
  "sql_query": "SELECT COUNT(user_id) FROM users WHERE signup_date >= date_trunc('month', current_date - interval '1 month') AND signup_date < date_trunc('month', current_date);", // Example SQL
  "result": "[{\"count\": 120}]", // Example result (often a JSON string of the SQL output)
  "context_from_vector_db": "Table: users (Schema: public)\nColumns:\n  - user_id (integer): Unique identifier for the user.\n  - username (text)\n  - signup_date (date): Date when the user signed up.\n...", // Snippets of schema used as context
  "error": null // Or an error message if something went wrong
}
```
*   `natural_language_query`: Your original query.
*   `sql_query`: The SQL query generated by the LLM agent (best effort extraction).
*   `result`: The result returned from executing the SQL query. The format can vary depending on the query and the agent's output.
*   `context_from_vector_db`: The schema information retrieved from ChromaDB that was provided to the LLM.
*   `error`: Any error message if the query processing failed.

### 2. Checking Service Health

You can check the status of the application and its components by accessing the `/health` endpoint.

**Example using `curl`:**

```bash
curl http://localhost:8000/health
```

**Example Response:**

```json
{
  "status": "ok", // or "degraded", "error"
  "services": {
    "llm": "Initialized",
    "embeddings_model": "Initialized",
    "sql_database_engine": "Initialized",
    "vector_store": "Initialized",
    "qa_chain": "Initialized",
    "sql_agent_executor": "Initialized",
    "postgresql_connection": "OK",
    "chromadb_connection": "OK"
  }
}
```

## Environment Variables

The following environment variables are crucial for configuring the application, primarily set in the `.env` file:

*   **`POSTGRES_USER`**: Username for the PostgreSQL database. (Default: `user`)
*   **`POSTGRES_PASSWORD`**: Password for the PostgreSQL database. (Default: `password`)
*   **`POSTGRES_DB`**: Name of the PostgreSQL database. (Default: `ragdb`)
*   **`OPENAI_API_KEY`**: Your API key for OpenAI services (embeddings and LLM). **Required.**
*   **`PYTHONUNBUFFERED`**: Set to `1` to ensure Python output (like logs) is sent directly to the terminal without buffering, which is useful in Docker. (Default: `1`)

These variables are used by `docker-compose.yml` to configure the services. The `app` service also uses these (or derived versions like `DATABASE_URL`) to connect to other services. Internally, the `app` service connects to:
*   PostgreSQL via `DB_HOST=db` (service name) and `DB_PORT=5432`.
*   ChromaDB via `CHROMA_HOST=chroma` (service name) and `CHROMA_PORT=8000` (internal Chroma port).

## Project Structure

```
.
├── .env.example         # Example environment variables
├── .env                 # Actual environment variables (ignored by git)
├── Dockerfile           # Docker build definition for the FastAPI application
├── README.md            # This file
├── docker-compose.yml   # Docker Compose configuration for services (app, db, chroma)
├── main.py              # FastAPI application: API endpoints, LangChain RAG logic
├── metadata_extractor.py # Logic for extracting schema from PostgreSQL
├── requirements.txt     # Python dependencies
└── init.sql             # Optional: Example SQL script to initialize the database
```

*   **`main.py`**: Core FastAPI application containing API endpoints (`/query`, `/health`) and the main RAG orchestration logic using LangChain. Initializes and uses components like the LLM, embedding model, vector store, and SQL agent.
*   **`metadata_extractor.py`**: Contains functions to connect to the PostgreSQL database and extract its schema (tables, columns, types, comments, views). This information is then used to populate the vector store.
*   **`Dockerfile`**: Instructions for building the Docker image for the `app` service. It installs Python, copies the application code, and sets the command to run Uvicorn.
*   **`docker-compose.yml`**: Defines and configures the multi-container Docker application:
    *   `app`: The FastAPI/LangChain application.
    *   `db`: The PostgreSQL database service.
    *   `chroma`: The ChromaDB vector store service.
    *   Includes network configuration and volume mounts for data persistence.
*   **`requirements.txt`**: Lists all Python dependencies required for the project.
*   **`.env.example` / `.env`**: Used to manage environment-specific configurations like API keys and database credentials.

## Local Development (Alternative to Full Docker Setup)

While Docker is recommended for ease of deployment and consistency, you can run the FastAPI application (`main.py`) locally for development if you have Python, PostgreSQL, and ChromaDB installed and running on your machine.

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
2.  **Set Environment Variables:**
    *   Ensure `OPENAI_API_KEY` is set in your environment.
    *   You'll need to configure database connection variables (e.g., `DB_HOST=localhost`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`) and ChromaDB connection variables (`CHROMA_HOST=localhost`, `CHROMA_PORT` for the host-exposed Chroma port, e.g., 8001 if using the provided docker-compose for Chroma only).
    *   You can create a `.env` file in the project root and `main.py` (if modified or using `python-dotenv` directly in its `if __name__ == "__main__":` block) can load it.
3.  **Run PostgreSQL and ChromaDB:**
    *   Start your local PostgreSQL instance.
    *   Start your local ChromaDB instance (or you could run just the `db` and `chroma` services from `docker-compose.yml`).
4.  **Run the FastAPI App:**
    ```bash
    # Ensure your .env is configured for local hosts for DB and Chroma
    # For example, in .env:
    # DB_HOST=localhost
    # CHROMA_HOST=localhost
    # CHROMA_PORT=8001 # Assuming Chroma is mapped to 8001 on host
    # POSTGRES_PORT=5432

    uvicorn main:app --reload --host 0.0.0.0 --port 8000
    ```
    The `if __name__ == "__main__":` block in `main.py` and `metadata_extractor.py` provide examples/stubs for how this might be initiated, but the primary execution path is via Uvicorn as specified in the `Dockerfile` and `CMD`.

## Troubleshooting

*   **OpenAI API Key Issues:**
    *   Ensure `OPENAI_API_KEY` is correctly set in your `.env` file and that the key is valid and has credits.
    *   Error messages like `AuthenticationError` or `RateLimitError` from OpenAI will appear in `app` logs.
*   **Service Connection Issues (app can't reach db or chroma):**
    *   Check `docker-compose logs app`.
    *   Ensure services are running: `docker-compose ps`.
    *   Verify Docker networking. Usually, Docker Compose handles this, but complex local network configurations might interfere.
    *   The `app` service connects to `db` on host `db` and `chroma` on host `chroma` (their service names within the Docker network).
*   **Database Schema Not Loaded / Empty Context:**
    *   Ensure your PostgreSQL database (`db` service) actually has tables and views defined. If it's empty, the RAG system has no schema to learn. See "Initialize Database with Schema/Data".
    *   Check `docker-compose logs app` during startup for messages from `metadata_extractor.py` about schema loading.
    *   Restart the `app` service after making schema changes: `docker-compose restart app`.
*   **ChromaDB Errors:**
    *   Check `docker-compose logs chroma`.
    *   Ensure the `chroma_data` volume has correct permissions if you've modified its setup.
*   **Viewing Logs:**
    *   For the application: `docker-compose logs -f app`
    *   For the database: `docker-compose logs -f db`
    *   For ChromaDB: `docker-compose logs -f chroma`
*   **Port Conflicts:**
    *   If ports `8000` (app), `8001` (Chroma host mapping), or `5432` (Postgres host mapping) are in use on your host machine, `docker-compose up` will fail. Change the host-side port mapping in `docker-compose.yml` (e.g., ` "8080:8000"`).

## Contributing

(If this were an open project, contribution guidelines would go here.)

## License

(Specify license information here, e.g., MIT License.)
