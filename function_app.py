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


@app.function_name(name="player_register")
@app.route(route="player/register", methods=["POST"])
def player_register(req: func.HttpRequest) -> func.HttpResponse:
    data = req.get_json()
    username = data["username"]
    password = data["password"]

    # Validation
    if len(username) < 5 or len(username) > 12:
        return func.HttpResponse(
            json.dumps({"result": False, "msg": "Username less than 5 characters or more than 12 characters"}),
            mimetype="application/json"
        )
    if len(password) < 8 or len(password) > 12:
        return func.HttpResponse(
            json.dumps({"result": False, "msg": "Password less than 8 characters or more than 12 characters"}),
            mimetype="application/json"
        )

    # Checking if that username is alredy used
    query = "SELECT * FROM players p WHERE p.username = @username"
    params = [{"name": "@username", "value": username}]
    items = list(player_container.query_items(query=query, parameters=params, enable_cross_partition_query=True))

    if len(items) > 0:
        return func.HttpResponse(
            json.dumps({"result": False, "msg": "Username already exists"}),
            mimetype="application/json"
        )

    # Create new player
    player_doc = {
        "id": username,
        "username": username,
        "password": password,
        "games_played": 0,
        "total_score": 0
    }
    player_container.create_item(player_doc)

    return func.HttpResponse(
        json.dumps({"result": True, "msg": "OK"}),
        mimetype="application/json"
    )