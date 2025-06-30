import os
from sqlalchemy import create_engine, text
from langchain.docstore.document import Document
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db_connection_url():
    """Constructs database connection URL from environment variables."""
    db_user = os.getenv("POSTGRES_USER", "user")
    db_password = os.getenv("POSTGRES_PASSWORD", "password")
    db_host = os.getenv("DB_HOST", "db") # Docker service name for the DB
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("POSTGRES_DB", "ragdb")
    return f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

def extract_metadata(engine):
    """
    Extracts schema metadata (tables, columns, types, comments) and view definitions
    from the PostgreSQL database.
    """
    documents = []

    # SQL query to extract table and column information with comments
    # Note: pg_catalog.pg_description.description can be null
    table_column_query = text("""
    SELECT
        c.table_schema,
        c.table_name,
        c.column_name,
        c.data_type,
        COALESCE(pgd.description, '') AS column_comment,
        COALESCE(obj_description( ('"' || c.table_schema || '"."' || c.table_name || '"')::regclass::oid ), '') AS table_comment
    FROM information_schema.columns c
    LEFT JOIN pg_catalog.pg_statio_all_tables AS st
        ON c.table_schema = st.schemaname AND c.table_name = st.relname
    LEFT JOIN pg_catalog.pg_description pgd
        ON pgd.objoid = st.relid AND pgd.objsubid = c.ordinal_position
    WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
      AND c.table_schema NOT LIKE 'pg_temp_%'
    ORDER BY c.table_schema, c.table_name, c.ordinal_position;
    """)

    # SQL query to extract view information with comments
    view_query = text("""
    SELECT
        v.table_schema AS view_schema,
        v.table_name AS view_name,
        v.view_definition,
        COALESCE(obj_description( ('"' || v.table_schema || '"."' || v.table_name || '"')::regclass::oid ), '') AS view_comment
    FROM information_schema.views v
    WHERE v.table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
      AND v.table_schema NOT LIKE 'pg_temp_%'
    ORDER BY v.table_schema, v.table_name;
    """)

    with engine.connect() as connection:
        logger.info("Extracting table and column metadata...")
        try:
            result_tables_cols = connection.execute(table_column_query)
            tables_data = {}
            for row in result_tables_cols:
                schema, table, column, dtype, col_comment, tbl_comment = row
                table_key = f"{schema}.{table}"
                if table_key not in tables_data:
                    tables_data[table_key] = {
                        "schema": schema,
                        "name": table,
                        "comment": tbl_comment,
                        "columns": []
                    }
                tables_data[table_key]["columns"].append({
                    "name": column,
                    "type": dtype,
                    "comment": col_comment
                })

            for table_key, data in tables_data.items():
                table_doc_content = f"Table: {data['name']} (Schema: {data['schema']})\n"
                if data['comment']:
                    table_doc_content += f"Comment: {data['comment']}\n"
                table_doc_content += "Columns:\n"
                for col in data['columns']:
                    table_doc_content += f"  - {col['name']} ({col['type']})"
                    if col['comment']:
                        table_doc_content += f": {col['comment']}"
                    table_doc_content += "\n"
                documents.append(Document(page_content=table_doc_content.strip(), metadata={"source_type": "table", "table_name": data['name'], "schema_name": data['schema']}))
            logger.info(f"Successfully extracted metadata for {len(tables_data)} tables.")

        except Exception as e:
            logger.error(f"Error extracting table/column metadata: {e}")


        logger.info("Extracting view metadata...")
        try:
            result_views = connection.execute(view_query)
            view_count = 0
            for row in result_views:
                view_schema, view_name, view_def, view_comment = row
                view_doc_content = f"View: {view_name} (Schema: {view_schema})\n"
                if view_comment:
                    view_doc_content += f"Comment: {view_comment}\n"
                view_doc_content += f"Definition:\n{view_def}\n"
                # You might want to also extract columns of the view if needed, similar to tables.
                # For now, just the definition and comment.
                documents.append(Document(page_content=view_doc_content.strip(), metadata={"source_type": "view", "view_name": view_name, "schema_name": view_schema}))
                view_count += 1
            logger.info(f"Successfully extracted metadata for {view_count} views.")

        except Exception as e:
            logger.error(f"Error extracting view metadata: {e}")

    logger.info(f"Total documents created: {len(documents)}")
    if not documents:
        logger.warning("No metadata documents were created. Check database schema and permissions.")
    return documents

def load_schema_documents():
    """
    Main function to connect to DB and load schema documents.
    Called by the FastAPI app on startup.
    """
    db_url = get_db_connection_url()
    logger.info(f"Connecting to database at {db_url.replace(os.getenv('POSTGRES_PASSWORD', 'password'), '********')}") # Mask password in log
    try:
        engine = create_engine(db_url)
        # Test connection
        with engine.connect() as connection:
            logger.info("Successfully connected to the database.")

        schema_docs = extract_metadata(engine)
        if not schema_docs:
            logger.warning("No schema documents were extracted. The RAG system might not have enough context.")
            # Potentially return some default document or raise an error
            # For now, we'll return an empty list, and the app should handle it.
        return schema_docs
    except Exception as e:
        logger.error(f"Failed to connect to database or extract metadata: {e}")
        # Depending on desired behavior, you might want to re-raise or handle gracefully
        return [] # Return empty list on failure

if __name__ == "__main__":
    # This is for local testing of the script
    # Ensure DB is running and accessible, and .env file or environment variables are set
    logger.info("Running metadata_extractor.py directly for testing...")

    # For local testing, you might need to load .env if not using Docker Compose
    from dotenv import load_dotenv
    load_dotenv() # Load .env file from current directory

    # Override DB_HOST for local testing if PostgreSQL is running on localhost
    # and not in Docker network.
    # os.environ["DB_HOST"] = "localhost"

    docs = load_schema_documents()
    if docs:
        logger.info(f"\n--- Extracted {len(docs)} documents ---")
        for i, doc in enumerate(docs):
            logger.info(f"Document {i+1}:")
            logger.info(f"Content: \n{doc.page_content}")
            logger.info(f"Metadata: {doc.metadata}\n")
    else:
        logger.info("No documents extracted during local test.")

    # Example: Create a dummy table and view in your local 'ragdb' for testing
    # You'd typically run these SQL commands via psql or a DB tool before testing.
    # CREATE SCHEMA IF NOT EXISTS sales;
    # CREATE TABLE sales.contracts (
    #     contract_id SERIAL PRIMARY KEY,
    #     contract_name TEXT,
    #     status VARCHAR(50),
    #     signed_date DATE
    # );
    # COMMENT ON TABLE sales.contracts IS 'Stores information about sales contracts.';
    # COMMENT ON COLUMN sales.contracts.contract_id IS 'Unique identifier for the contract.';
    # COMMENT ON COLUMN sales.contracts.status IS 'Current status of the contract (e.g., Draft, Signed, Active, Expired).';

    # CREATE VIEW sales.active_contracts_view AS
    # SELECT contract_id, contract_name, signed_date
    # FROM sales.contracts
    # WHERE status = 'Active';
    # COMMENT ON VIEW sales.active_contracts_view IS 'A view showing currently active contracts.';

    # CREATE TABLE public.invoices (
    #   invoice_id SERIAL PRIMARY KEY,
    #   contract_id INT REFERENCES sales.contracts(contract_id),
    #   invoice_date DATE,
    #   amount DECIMAL(10,2)
    # );
    # COMMENT ON TABLE public.invoices IS 'Stores invoice data related to contracts.';
    # COMMENT ON COLUMN public.invoices.amount IS 'The total amount of the invoice.';

    # After creating these, running `python metadata_extractor.py` (with DB env vars set)
    # should print the extracted schema for these tables/views.
    # Remember to set POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, and potentially DB_HOST.
    # If testing outside Docker Compose, DB_HOST would typically be 'localhost'.
    # If testing with Docker Compose, ensure the 'db' service is up and this script
    # is run from within the 'app' service or with DB_HOST=localhost if ports are mapped.
    # For the main app, DB_HOST will be 'db' (the service name).

    # If you want to test connection to a DB service from your host machine before running docker-compose up,
    # you would need to temporarily expose the port of the DB service in docker-compose.yml
    # and set DB_HOST to localhost. For the app service, DB_HOST must be 'db'.
    # The current get_db_connection_url uses DB_HOST which defaults to "db", suitable for app container.
    # For local script testing against a Dockerized DB, you might need to change DB_HOST to "localhost"
    # if your PostgreSQL container's port 5432 is mapped to localhost:5432.
    # Example for local testing with .env:
    # POSTGRES_USER=user
    # POSTGRES_PASSWORD=password
    # POSTGRES_DB=ragdb
    # DB_HOST=localhost  # if psql is running on localhost or mapped from docker
    # DB_PORT=5432
    # OPENAI_API_KEY=your_key_here (not used by this script but good for .env)

    logger.info("Metadata extraction test finished.")
