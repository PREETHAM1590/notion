"""
Database connection test script.

This module provides a simple function to test connectivity to a PostgreSQL
database using credentials defined in a `.env` file. It uses the
``python‑dotenv`` package to load environment variables and the
``psycopg2`` library to create a connection. Running this script from the
command line will attempt to connect to the database, execute a simple
``SELECT NOW()`` query, print the current time returned by the server and
close the connection.

Environment variables required in the `.env` file include:

```
user=<username>
password=<password>
host=<hostname or IP address>
port=<database port, e.g. 5432>
dbname=<database name>
```

For example:

```
user=myuser
password=mysecretpassword
host=localhost
port=5432
dbname=mydatabase
```

Make sure to create a `.env` file at the root of the project (or in the
directory from which you run the script) with the appropriate values.

Note: This script is intended for development and testing. In production,
handle exceptions and sensitive data carefully.
"""

import os

import psycopg2
from dotenv import load_dotenv


def test_database_connection() -> None:
    """Test a connection to the PostgreSQL database and print the current time.

    Loads configuration from a `.env` file, attempts to connect to the
    database using the provided credentials, and executes a simple query
    (``SELECT NOW()``) to retrieve the current server time. Prints
    diagnostic messages about the connection status and gracefully
    closes the connection.
    """
    # Load environment variables from .env
    load_dotenv()

    # Fetch variables
    user = os.getenv("user")
    password = os.getenv("password")
    host = os.getenv("host")
    port = os.getenv("port")
    dbname = os.getenv("dbname")

    try:
        # Connect to the database
        connection = psycopg2.connect(
            user=user,
            password=password,
            host=host,
            port=port,
            dbname=dbname,
        )
        print("Connection successful!")

        # Create a cursor to execute SQL queries
        cursor = connection.cursor()

        # Example query
        cursor.execute("SELECT NOW();")
        result = cursor.fetchone()
        print("Current Time:", result)

        # Close the cursor and connection
        cursor.close()
        connection.close()
        print("Connection closed.")

    except Exception as exc:
        print(f"Failed to connect: {exc}")


if __name__ == "__main__":
    # Run the test when executed as a script
    test_database_connection()