import unittest
import requests
import json
from azure.cosmos import CosmosClient

class TestPlayerLoginFunction(unittest.TestCase):
    LOCAL_DEV_URL = "http://localhost:7071/player/login"
    PUBLIC_URL = "<Your deployment URL here>/user/add"
    TEST_URL = LOCAL_DEV_URL

    # Initialize Cosmos client and containers once per class
    with open('local.settings.json') as settings_file:
        settings = json.load(settings_file)

    MyCosmos = CosmosClient.from_connection_string(
        settings['Values']['AzureCosmosDBConnectionString']
    )
    Database = MyCosmos.get_database_client(settings['Values']['DatabaseName'])
    player_container = Database.get_container_client(settings['Values']['PlayerContainerName'])
    prompt_container = Database.get_container_client(settings['Values']['PromptContainerName'])

    def setUp(self):
        """Clean up both containers before each test."""
        # Clear players
        for item in self.player_container.query_items(
                query="SELECT * FROM c",
                enable_cross_partition_query=True):
            self.player_container.delete_item(item, partition_key=item["id"])
        
        # Clear prompts
        for item in self.prompt_container.query_items(
                query="SELECT * FROM c",
                enable_cross_partition_query=True):
            self.prompt_container.delete_item(item, partition_key=item["username"])
        # create user
        payload = {"username": "player01", "password": "password1"}
        requests.post("http://localhost:7071/player/register", json=payload)

    def test_validLogin(self):
        payload = {"username": "player01", "password": "password1"}
        response = requests.post(self.TEST_URL,json=payload)
        data = response.json()
        self.assertTrue(data["result"])
        self.assertEqual(data["msg"], "OK")

        



