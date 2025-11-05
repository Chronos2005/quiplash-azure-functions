import unittest
from azure.cosmos import CosmosClient
import json
import requests

class TestPlayerRegisterFunction(unittest.TestCase):
    LOCAL_DEV_URL = "http://localhost:7071/player/register"
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

    def test_valid_registration(self):
        """Test that a valid player can be successfully registered."""
        payload = {"username": "player01", "password": "password1"}
        response = requests.post(self.TEST_URL, json=payload)


        # Correct JSON output
        data = response.json()
        self.assertTrue(data["result"])
        self.assertEqual(data["msg"], "OK")

        # Check DB for new player
        query = f"SELECT * FROM c WHERE c.username = '{payload['username']}'"
        results = list(self.player_container.query_items(
            query=query, enable_cross_partition_query=True))

        self.assertEqual(len(results), 1, "Player not inserted in DB")
        player_doc = results[0]

        # Validate fields
        self.assertEqual(player_doc["username"], payload["username"])
        self.assertIn("password", player_doc)
        self.assertIn("games_played", player_doc)
        self.assertIn("total_score", player_doc)

        self.assertEqual(player_doc["games_played"], 0)
        self.assertEqual(player_doc["total_score"], 0)
    
    def test_duplicate_username(self):
        """Test that registering an existing username returns the correct error message."""

        payload = {"username": "player01", "password": "password1"}

        # First registration should succeed
        first_response = requests.post(self.TEST_URL, json=payload)
        self.assertEqual(first_response.status_code, 200)
        first_data = first_response.json()
        self.assertTrue(first_data["result"])
        self.assertEqual(first_data["msg"], "OK")

        # Second registration with the same username should fail
        duplicate_response = requests.post(self.TEST_URL, json=payload)
        self.assertEqual(duplicate_response.status_code, 200)

        # Verify correct JSON error message
        dup_data = duplicate_response.json()
        self.assertFalse(dup_data["result"], "Expected result to be false for duplicate username")
        self.assertEqual(dup_data["msg"], "Username already exists")

        # Ensure only one record exists in DB
        query = f"SELECT * FROM c WHERE c.username = '{payload['username']}'"
        results = list(self.player_container.query_items(query=query, enable_cross_partition_query=True))
        self.assertEqual(len(results), 1, "Duplicate user should not be inserted again")

    def test_username_too_short(self):
        """Test that usernames shorter than 5 characters are rejected."""
        payload = {"username": "abc", "password": "password1"}
        response = requests.post(self.TEST_URL, json=payload)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertFalse(data["result"])
        self.assertEqual(data["msg"], "Username less than 5 characters or more than 12 characters")

    def test_username_too_long(self):
        """Test that usernames longer than 12 characters are rejected."""
        payload = {"username": "thisisaverylongusername", "password": "password1"}
        response = requests.post(self.TEST_URL, json=payload)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertFalse(data["result"])
        self.assertEqual(data["msg"], "Username less than 5 characters or more than 12 characters")

    def test_password_too_short_or_long(self):
        """Test that passwords outside the 8–12 character range are rejected."""
        # Too short
        payload_short = {"username": "validuser", "password": "short"}
        response_short = requests.post(self.TEST_URL, json=payload_short)
        self.assertEqual(response_short.status_code, 200)
        data_short = response_short.json()
        self.assertFalse(data_short["result"])
        self.assertEqual(data_short["msg"], "Password less than 8 characters or more than 12 characters")

        # Too long
        payload_long = {"username": "validuser2", "password": "thispasswordistoolong"}
        response_long = requests.post(self.TEST_URL, json=payload_long)
        self.assertEqual(response_long.status_code, 200)
        data_long = response_long.json()
        self.assertFalse(data_long["result"])
        self.assertEqual(data_long["msg"], "Password less than 8 characters or more than 12 characters")

