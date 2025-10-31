import azure.functions as func
import datetime
import json
import logging
from azure.cosmos import CosmosClient
import os

app = func.FunctionApp()

#Setting up database accss
COSMOS_CONN_STR = os.environ.get("AzureCosmosDBConnectionString")
DATABASE_NAME = os.environ.get("DatabaseName")
PLAYER_CONTAINER_NAME = os.environ.get("PlayerContainerName")
PROMPT_CONTAINER_NAME = os.environ.get("PromptContainerName")

# Connect to Cosmos DB account
client = CosmosClient.from_connection_string(COSMOS_CONN_STR)

# Access the database
database = client.get_database_client(DATABASE_NAME)

# Access containers
player_container = database.get_container_client(PLAYER_CONTAINER_NAME)
prompt_container = database.get_container_client(PROMPT_CONTAINER_NAME)
