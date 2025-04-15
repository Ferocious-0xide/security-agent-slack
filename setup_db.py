from mock_charlotte import setup_database
from seed_knowledge import seed_database

if __name__ == "__main__":
    print("Setting up database...")
    setup_database()
    print("Seeding initial data...")
    seed_database()
    print("Setup complete!") 