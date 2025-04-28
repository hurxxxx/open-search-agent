#!/bin/bash

# Display banner
echo "====================================="
echo "  Starting AI Web Search Agent Backend"
echo "====================================="

cd backend 
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
