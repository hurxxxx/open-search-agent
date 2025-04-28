try:
    from app.main import app
    print("Successfully imported app")
except Exception as e:
    print(f"Error importing app: {e}")
