// Configuration
const API_BASE_URL = 'http://localhost:8000/api/v1';
let apiKey = 'test_api_key_123'; // Default API key matching the one in backend/.env

// DOM Elements
const searchForm = document.getElementById('search-form');
const promptInput = document.getElementById('prompt');
const searchProviderSelect = document.getElementById('search-provider');
const searchButton = document.getElementById('search-button');
const loginButton = document.getElementById('login-button');
const usernameInput = document.getElementById('username');
const passwordInput = document.getElementById('password');
const authStatus = document.getElementById('auth-status');
const apiKeyInput = document.getElementById('api-key');
const saveApiKeyButton = document.getElementById('save-api-key-button');
const apiKeyStatus = document.getElementById('api-key-status');
const resultsSection = document.getElementById('results-section');
const loadingElement = document.getElementById('loading');
const resultsElement = document.getElementById('results');
const reportElement = document.getElementById('report');
const stepsContainer = document.getElementById('steps-container');
const sourcesList = document.getElementById('sources-list');

// Event Listeners
document.addEventListener('DOMContentLoaded', () => {
    searchForm.addEventListener('submit', handleSearch);
    saveApiKeyButton.addEventListener('click', handleSaveApiKey);

    // Check if we have an API key in localStorage
    const savedApiKey = localStorage.getItem('apiKey');
    if (savedApiKey) {
        apiKey = savedApiKey;
        apiKeyInput.value = apiKey;
        updateApiKeyStatus(true);
    }
});

// API Key Functions
function handleSaveApiKey() {
    const newApiKey = apiKeyInput.value.trim();

    if (!newApiKey) {
        updateApiKeyStatus(false, 'API key cannot be empty');
        return;
    }

    // Save the API key
    apiKey = newApiKey;
    localStorage.setItem('apiKey', apiKey);
    updateApiKeyStatus(true, 'API key saved successfully');
}

function updateApiKeyStatus(isSuccess, message = '') {
    apiKeyStatus.textContent = message || (isSuccess ? 'API key is set' : 'API key is not set');
    apiKeyStatus.className = isSuccess ? 'auth-success' : 'auth-error';

    // Update UI based on API key status
    if (isSuccess) {
        saveApiKeyButton.textContent = 'API Key Saved';
        setTimeout(() => {
            saveApiKeyButton.textContent = 'Save API Key';
        }, 2000);
    }
}

// Search Functions
async function handleSearch(event) {
    event.preventDefault();

    const prompt = promptInput.value.trim();
    if (!prompt) {
        alert('Please enter a question');
        return;
    }

    // If API key is not available, require it
    if (!apiKey) {
        alert('Please set an API key first');
        return;
    }

    // Show loading state
    resultsSection.style.display = 'block';
    loadingElement.style.display = 'block';
    resultsElement.style.display = 'none';

    try {
        // Get the selected search provider
        const searchProvider = searchProviderSelect.value;

        // Create headers with search provider preference and Bearer token
        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${apiKey}`,  // Use Bearer token authentication
            'X-Search-Provider': searchProvider
        };

        const response = await fetch(`${API_BASE_URL}/search`, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({ prompt })
        });

        if (!response.ok) {
            throw new Error('Search request failed');
        }

        const data = await response.json();

        // Add the search provider info to the results display
        data.searchProvider = searchProvider;
        displayResults(data);
    } catch (error) {
        console.error('Search error:', error);
        alert(`Error: ${error.message || 'Failed to perform search'}`);
        resultsSection.style.display = 'none';
    } finally {
        loadingElement.style.display = 'none';
    }
}

function displayResults(data) {
    // Display the final report with search provider info
    const providerInfo = data.searchProvider ?
        `<div class="search-provider-info">Search Provider: <strong>${data.searchProvider}</strong></div>` : '';
    reportElement.innerHTML = providerInfo + formatMarkdown(data.final_report);

    // Display search steps
    stepsContainer.innerHTML = '';
    data.search_steps.forEach(step => {
        const stepElement = document.createElement('div');
        stepElement.className = 'step';

        const sufficientClass = step.sufficient ? 'sufficient-true' : 'sufficient-false';
        const sufficientText = step.sufficient ? 'Sufficient' : 'Insufficient';

        stepElement.innerHTML = `
            <div class="step-query">
                Query: ${escapeHTML(step.query)}
                <span class="step-sufficient ${sufficientClass}">${sufficientText}</span>
            </div>
            <div class="step-reasoning">${escapeHTML(step.reasoning)}</div>
        `;

        stepsContainer.appendChild(stepElement);
    });

    // Display sources
    sourcesList.innerHTML = '';
    data.sources.forEach(source => {
        const sourceItem = document.createElement('li');
        sourceItem.innerHTML = `
            <a href="${escapeHTML(source.link)}" target="_blank">${escapeHTML(source.title)}</a>
            <p>${escapeHTML(source.snippet)}</p>
        `;
        sourcesList.appendChild(sourceItem);
    });

    // Show results
    resultsElement.style.display = 'block';
}

// Helper Functions
function escapeHTML(str) {
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function formatMarkdown(text) {
    // Very simple markdown formatting
    return text
        // Headers
        .replace(/^### (.*$)/gim, '<h3>$1</h3>')
        .replace(/^## (.*$)/gim, '<h2>$1</h2>')
        .replace(/^# (.*$)/gim, '<h1>$1</h1>')
        // Bold
        .replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>')
        // Italic
        .replace(/\*(.*?)\*/gim, '<em>$1</em>')
        // Links
        .replace(/\[([^\]]+)\]\(([^)]+)\)/gim, '<a href="$2" target="_blank">$1</a>')
        // Lists
        .replace(/^\s*\d+\.\s+(.*$)/gim, '<ol><li>$1</li></ol>')
        .replace(/^\s*[\-\*]\s+(.*$)/gim, '<ul><li>$1</li></ul>')
        // Paragraphs
        .replace(/\n\s*\n/gim, '</p><p>')
        // Line breaks
        .replace(/\n/gim, '<br>');
}
