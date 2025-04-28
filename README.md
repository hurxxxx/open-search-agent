# AI Web Search Agent

An AI-powered web search agent that uses OpenAI's LLM to decompose user prompts, perform targeted searches, and generate comprehensive reports.

## Features

- **Prompt Decomposition**: Breaks down complex user queries into targeted search terms
- **Iterative Search**: Performs searches and evaluates if results are sufficient to answer the original prompt
- **Adaptive Search Refinement**: Modifies search queries based on evaluation of search results
- **Comprehensive Report Generation**: Synthesizes search results into a detailed report
- **OpenAPI Specification**: API follows OpenAPI standards for easy integration
- **Authentication**: Secure API access with JWT authentication
- **Environment-based Configuration**: Uses .env files for configuration management

## Project Structure

```
open-search-agent/
├── backend/               # Python FastAPI backend
│   ├── app/               # Application code
│   │   ├── api/           # API routes and dependencies
│   │   ├── core/          # Core functionality (config, security)
│   │   ├── models/        # Data models and schemas
│   │   ├── services/      # Business logic services
│   │   └── main.py        # Application entry point
│   ├── tests/             # Test suite
│   ├── .env               # Environment variables
│   └── requirements.txt   # Python dependencies
├── frontend/              # Simple web UI
│   ├── index.html         # HTML structure
│   ├── styles.css         # CSS styling
│   └── script.js          # JavaScript functionality
└── README.md              # Project documentation
```

## Getting Started

### Prerequisites

- Python 3.8+
- OpenAI API key
- Google Custom Search API key and Search Engine ID

### Installation

1. Clone the repository:
   ```
   git clone https://github.com/hurxxxx/open-search-agent.git
   cd open-search-agent
   ```

2. Set up the backend:
   ```
   cd backend
   pip install -r requirements.txt
   ```

3. Configure environment variables:
   - Copy `.env.example` to `.env`
   - Fill in your API keys and other configuration

### Running the Application

1. Start the backend server:
   ```
   cd backend
   uvicorn app.main:app --reload
   ```

2. Open the frontend:
   - Open `frontend/index.html` in your web browser
   - Or serve it using a simple HTTP server:
     ```
     cd frontend
     python -m http.server
     ```

## API Documentation

Once the server is running, you can access the OpenAPI documentation at:
```
http://localhost:8000/api/v1/openapi.json
```

Or the Swagger UI at:
```
http://localhost:8000/docs
```

## Authentication

The API supports two authentication methods:

### Method 1: API Key Authentication (Recommended)

This is a simple token-based authentication that doesn't require a database:

1. Set the `API_KEY` in your `.env` file
2. Include the API key in the `X-API-Key` header for your requests:
   ```
   X-API-Key: your_api_key_here
   ```

### Method 2: JWT Authentication (Legacy)

The API also supports JWT token-based authentication:

1. Make a POST request to `/api/v1/auth/login` with username and password
2. Use the returned token in the Authorization header for subsequent requests:
   ```
   Authorization: Bearer your_token_here
   ```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgements

- OpenAI for providing the LLM API
- Google for the Custom Search API
- FastAPI for the web framework
