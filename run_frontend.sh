#!/bin/bash

# Display banner
echo "====================================="
echo "  Starting AI Web Search Agent Frontend"
echo "====================================="
cd frontend 
python3 -m http.server 8080
