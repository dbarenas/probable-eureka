import os
import logging
from fastapi import FastAPI, HTTPException, Depends, status
from pydantic import BaseModel
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any

from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.vectorstores.chroma import Chroma
from langchain.chains import RetrievalQA
from langchain.sql_database import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit # Updated import
from langchain.agents import create_sql_agent # Updated agent creation

from metadata_extractor import load_schema_documents, get_db_connection_url
from langchain.docstore.document import Document # For type hinting

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Global variables to hold LangChain components ---
# These will be initialized during startup
db_engine: Optional[SQLDatabase] = None
vectorstore: Optional[Chroma] = None
qa_chain: Optional[RetrievalQA] = None
sql_agent_executor: Optional[Any] = None # Type Any for agent executor
llm: Optional[ChatOpenAI] = None
embeddings_model: Optional[OpenAIEmbeddings] = None

# --- Pydantic Models ---
class QueryRequest(BaseModel):
    natural_language_query: str

class QueryResponse(BaseModel):
    natural_language_query: str
    sql_query: Optional[str] = None
    result: Optional[Any] = None
    context_from_vector_db: Optional[str] = None
    error: Optional[str] = None

class HealthCheckResponse(BaseModel):
    status: str
    services: Dict[str, str]


# --- Helper function to initialize resources ---
def initialize_rag_components():
    global db_engine, vectorstore, qa_chain, sql_agent_executor, llm, embeddings_model

    logger.info("Initializing RAG components...")

    # 0. Load Environment Variables
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        logger.error("OPENAI_API_KEY environment variable not set.")
        raise ValueError("OPENAI_API_KEY is required.")

    db_url = get_db_connection_url()
    chroma_host = os.getenv("CHROMA_HOST", "chroma")
    chroma_port = os.getenv("CHROMA_PORT", "8000")

    logger.info(f"Database URL (password masked): {db_url.replace(os.getenv('POSTGRES_PASSWORD', 'password'), '********')}")
    logger.info(f"Chroma Host: {chroma_host}, Port: {chroma_port}")

    # 1. Initialize LLM and Embeddings
    try:
        llm = ChatOpenAI(temperature=0, model_name="gpt-3.5-turbo", openai_api_key=openai_api_key)
        embeddings_model = OpenAIEmbeddings(openai_api_key=openai_api_key)
        logger.info("LLM and Embeddings models initialized.")
    except Exception as e:
        logger.error(f"Error initializing OpenAI models: {e}")
        raise

    # 2. Connect to PostgreSQL for SQL Agent
    try:
        db_engine = SQLDatabase.from_uri(db_url)
        # Test connection
        logger.info(f"Dialect: {db_engine.dialect}")
        logger.info(f"Sample tables (initially, before metadata script may have run fully): {db_engine.get_usable_table_names()}")
        logger.info("SQLDatabase engine initialized for LangChain.")
    except Exception as e:
        logger.error(f"Error initializing SQLDatabase engine: {e}")
        # This is critical, so we should probably not continue if DB isn't available
        raise

    # 3. Load schema metadata from DB and store in Chroma
    # This relies on the DB service being up and accessible
    max_retries = 5
    retry_delay = 10 # seconds
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempt {attempt + 1}/{max_retries} to load schema documents...")
            schema_docs: List[Document] = load_schema_documents() # From metadata_extractor.py
            if not schema_docs:
                logger.warning("No schema documents were extracted. The vector store will be empty. This might be okay if the database is initially empty.")
                # Create a dummy document to prevent Chroma errors with empty list
                schema_docs = [Document(page_content="No schema information available.", metadata={"source_type": "placeholder"})]

            logger.info(f"Loaded {len(schema_docs)} schema documents.")

            # Initialize ChromaDB client and vector store
            # For persistent storage, ensure ChromaDB is running and accessible
            # and that a persistent path is configured in its deployment.
            vectorstore = Chroma(
                collection_name="schema_embeddings",
                embedding_function=embeddings_model,
                persist_directory=None, # Use client for service
                client_settings={ # For connecting to Chroma service
                    "chroma_server_host": chroma_host,
                    "chroma_server_http_port": chroma_port,
                }
            )
            # Check if collection exists, if not, add documents.
            # This simple check might not be robust for all scenarios.
            # A more robust way would be to manage collection creation/deletion as needed.
            try:
                if vectorstore._collection.count() == 0 or True: # For now, always try to re-add.
                                                                 # Consider a flag or versioning for schema updates.
                    logger.info("Adding schema documents to ChromaDB. This may take a moment...")
                    vectorstore.add_documents(schema_docs) # This can take time for many docs
                    # vectorstore.persist() # Not needed when using client in service mode
                    logger.info("Schema documents embedded and stored in ChromaDB.")
                else:
                    logger.info("Existing collection found in ChromaDB with documents. Skipping add.")

            except Exception as e: # Catch specific Chroma client errors if possible
                logger.error(f"Error interacting with ChromaDB: {e}")
                # Fallback to in-memory if connection fails, for resilience (optional)
                # logger.warning("Falling back to in-memory FAISS vector store due to Chroma connection error.")
                # from langchain.vectorstores import FAISS
                # vectorstore = FAISS.from_documents(schema_docs, embeddings_model)
                raise # Re-raise for now, as Chroma is a defined service.

            logger.info("Vector store initialized.")
            break # Success
        except Exception as e:
            logger.error(f"Error during schema loading or vector store initialization (attempt {attempt + 1}): {e}")
            if attempt + 1 == max_retries:
                logger.error("Max retries reached. Failed to initialize vector store with schema documents.")
                raise # Propagate the error to stop app startup if critical
            logger.info(f"Retrying in {retry_delay} seconds...")
            import time
            time.sleep(retry_delay)


    # 4. Setup Retriever and QA Chain
    if vectorstore:
        retriever = vectorstore.as_retriever(search_kwargs={"k": 3}) # Retrieve top 3 relevant docs
        qa_chain = RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff", # "stuff" is simplest, consider map_reduce for large docs
            retriever=retriever,
            return_source_documents=True # Good for debugging
        )
        logger.info("RetrievalQA chain initialized.")
    else:
        logger.error("Vector store not initialized. QA chain cannot be created.")
        # This is a critical failure for the RAG part.
        raise ConnectionError("Failed to initialize vector store. QA chain setup aborted.")


    # 5. Setup LangChain SQL Agent
    if db_engine and llm:
        toolkit = SQLDatabaseToolkit(db=db_engine, llm=llm)
        # Using the new way to create SQL agent
        sql_agent_executor = create_sql_agent(
            llm=llm,
            toolkit=toolkit,
            verbose=True,
            agent_type="openai-tools", # Or "openai-functions" or other compatible types
            # handle_parsing_errors=True # Useful for robustness
        )
        logger.info("SQL Agent executor initialized.")
    else:
        logger.error("SQLDatabase engine or LLM not initialized. SQL Agent cannot be created.")
        # Critical failure for SQL interaction part.
        raise ConnectionError("Failed to initialize DB engine or LLM. SQL Agent setup aborted.")

    logger.info("All RAG components initialized successfully.")


# --- FastAPI Lifespan Events ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup...")
    try:
        initialize_rag_components()
        logger.info("RAG components initialization complete.")
    except Exception as e:
        logger.critical(f"Failed to initialize RAG components during startup: {e}", exc_info=True)
        # Depending on policy, either exit or run in a degraded state
        # For now, we let it crash if critical components fail, Docker will restart.
        raise
    yield
    # --- Cleanup (if any) ---
    logger.info("Application shutdown...")
    if vectorstore and isinstance(vectorstore, Chroma):
        # Chroma client doesn't have explicit close. Persist is handled by server.
        logger.info("Chroma client does not require explicit close for service connection.")
    logger.info("Shutdown complete.")

app = FastAPI(lifespan=lifespan)

# --- Health Check Endpoint ---
@app.get("/health", response_model=HealthCheckResponse, status_code=status.HTTP_200_OK)
async def health_check():
    services_status = {
        "llm": "Initialized" if llm else "Not Initialized",
        "embeddings_model": "Initialized" if embeddings_model else "Not Initialized",
        "sql_database_engine": "Initialized" if db_engine and db_engine.engine else "Not Initialized",
        "vector_store": "Initialized" if vectorstore else "Not Initialized",
        "qa_chain": "Initialized" if qa_chain else "Not Initialized",
        "sql_agent_executor": "Initialized" if sql_agent_executor else "Not Initialized",
    }
    # Check DB connection
    db_ok = False
    if db_engine and db_engine.engine:
        try:
            with db_engine.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            db_ok = True
            services_status["postgresql_connection"] = "OK"
        except Exception as e:
            logger.warning(f"Health check: PostgreSQL connection failed: {e}")
            services_status["postgresql_connection"] = f"Error: {e}"
    else:
        services_status["postgresql_connection"] = "Not Initialized"

    # Check Chroma connection (basic)
    chroma_ok = False
    if vectorstore and isinstance(vectorstore, Chroma): # Check if it's Chroma
        try:
            vectorstore._client.heartbeat() # Chroma client heartbeat
            chroma_ok = True
            services_status["chromadb_connection"] = "OK"
        except Exception as e:
            logger.warning(f"Health check: ChromaDB connection failed: {e}")
            services_status["chromadb_connection"] = f"Error: {e}"
    else:
        services_status["chromadb_connection"] = "Not Initialized or not Chroma"

    app_status = "ok"
    if not all([llm, embeddings_model, db_engine, vectorstore, qa_chain, sql_agent_executor, db_ok, chroma_ok]):
        app_status = "degraded"
        if not any([llm, embeddings_model, db_engine, vectorstore, qa_chain, sql_agent_executor]):
            app_status = "error"

    return HealthCheckResponse(status=app_status, services=services_status)

# --- Main Query Endpoint ---
@app.post("/query", response_model=QueryResponse)
async def handle_query(request: QueryRequest):
    global qa_chain, sql_agent_executor

    if not qa_chain or not sql_agent_executor or not llm:
        logger.error("RAG components not initialized. Cannot process query.")
        raise HTTPException(status_code=503, detail="Service not fully initialized. Please try again later.")

    natural_query = request.natural_language_query
    logger.info(f"Received natural language query: {natural_query}")

    context_docs_str = "No context retrieved."
    try:
        # 1. Retrieve context from Vector DB using QA chain (retriever part)
        logger.info("Step 1: Retrieving context from vector store...")
        qa_result = await qa_chain.ainvoke({"query": natural_query}) # Use ainvoke for async

        # qa_result will contain 'source_documents' and 'result' (answer from LLM based on context)
        # We are interested in 'source_documents' for the SQL agent's context
        source_documents = qa_result.get("source_documents", [])
        if source_documents:
            context_docs_str = "\n---\n".join([doc.page_content for doc in source_documents])
            logger.info(f"Retrieved context: \n{context_docs_str}")
        else:
            logger.info("No relevant context documents found in vector store.")

    except Exception as e:
        logger.error(f"Error during context retrieval: {e}", exc_info=True)
        # Proceed without schema context, or return error based on policy
        # For now, we'll proceed, but log that context might be missing.
        context_docs_str = f"Error retrieving context: {e}. Proceeding without schema context."


    # 2. Formulate and execute SQL query using SQL Agent
    #    The prompt for the SQL agent should combine the schema context and the user query.
    #    The architecture plan suggests: agent_executor.run(f"{context}\nAnswer this using SQL and show results.")
    #    However, modern LangChain agents work better if the context is part of the system message or tool description.
    #    For create_sql_agent, it primarily uses the DB schema directly.
    #    We can pass the retrieved context as part of the input to the agent.

    prompt_for_sql_agent = (
        f"Based on the following potentially relevant schema information:\n"
        f"--- SCHEMA CONTEXT START ---\n{context_docs_str}\n--- SCHEMA CONTEXT END ---\n\n"
        f"User query: {natural_query}\n\n"
        f"Generate a SQL query to answer the user query. Then execute it and return the result. "
        f"If the query asks for something not answerable by SQL or the schema, explain why."
    )

    logger.info("Step 2: Passing to SQL Agent for SQL generation and execution...")
    logger.info(f"Prompt for SQL Agent:\n{prompt_for_sql_agent}")

    try:
        # The SQL agent will try to generate SQL, execute it, and return the result.
        # The output of `create_sql_agent` is an AgentExecutor.
        # Its `ainvoke` method returns a dictionary, typically with "output" and "intermediate_steps".
        agent_response = await sql_agent_executor.ainvoke({"input": prompt_for_sql_agent})

        # The actual SQL query might be found in intermediate steps if the agent shows its work.
        # This depends on the agent type and verbosity.
        # For "openai-tools", the tool calls will contain the SQL.
        generated_sql = "SQL query not explicitly extracted from agent steps."
        if 'intermediate_steps' in agent_response:
            for step in agent_response['intermediate_steps']:
                # Look for tool calls that execute SQL
                if hasattr(step[0], 'tool') and step[0].tool == 'sql_db_query': # Example, actual tool name might differ
                    generated_sql = step[0].tool_input
                    break
                # For openai-tools, it might be in message logs
                if hasattr(step[0], 'log'):
                    # Example: "Invoking \"sql_db_query\" with `SELECT * FROM ...`"
                    log_entry = str(step[0].log)
                    if "Invoking \"sql_db_query\"" in log_entry and "with `" in log_entry:
                        try:
                            generated_sql = log_entry.split("with `")[1].split("`")[0]
                            break
                        except IndexError:
                            pass # Could not parse

        final_answer = agent_response.get("output", "No output from SQL agent.")
        logger.info(f"SQL Agent generated SQL (best effort extraction): {generated_sql}")
        logger.info(f"SQL Agent final answer: {final_answer}")

        return QueryResponse(
            natural_language_query=natural_query,
            sql_query=generated_sql,
            result=final_answer,
            context_from_vector_db=context_docs_str
        )

    except Exception as e:
        logger.error(f"Error during SQL agent execution: {e}", exc_info=True)
        return QueryResponse(
            natural_language_query=natural_query,
            context_from_vector_db=context_docs_str,
            error=f"Error in SQL agent: {str(e)}"
        )

if __name__ == "__main__":
    # This block is for local development without Docker, if needed.
    # Uvicorn is expected to run this file in the Docker setup.
    # For local: `OPENAI_API_KEY="your_key" uvicorn main:app --reload --port 8000`
    # Ensure PostgreSQL and ChromaDB are running and accessible locally.
    # You'd typically set DB_HOST=localhost, CHROMA_HOST=localhost in your .env for this.
    logger.info("Starting application directly (intended for Uvicorn in Docker). For local dev, use `uvicorn main:app --reload` with .env setup.")
    # Example:
    # import uvicorn
    # from dotenv import load_dotenv
    # load_dotenv() # Load .env file if you have one for local dev
    # os.environ["DB_HOST"] = os.getenv("DB_HOST_LOCAL", "localhost") # Example override for local
    # os.environ["CHROMA_HOST"] = os.getenv("CHROMA_HOST_LOCAL", "localhost") # Example override for local
    # uvicorn.run(app, host="0.0.0.0", port=8000)
