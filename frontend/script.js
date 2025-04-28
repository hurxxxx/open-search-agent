// Configuration
const API_BASE_URL = 'http://localhost:8000/api/v1';
let authToken = '';

// DOM Elements
const searchForm = document.getElementById('search-form');
const promptInput = document.getElementById('prompt');
const searchProviderSelect = document.getElementById('search-provider');
const searchButton = document.getElementById('search-button');
const loginButton = document.getElementById('login-button');
const usernameInput = document.getElementById('username');
const passwordInput = document.getElementById('password');
const authStatus = document.getElementById('auth-status');
const resultsSection = document.getElementById('results-section');
const loadingElement = document.getElementById('loading');
const resultsElement = document.getElementById('results');
const reportElement = document.getElementById('report');
const stepsContainer = document.getElementById('steps-container');
const sourcesList = document.getElementById('sources-list');

// Event Listeners
document.addEventListener('DOMContentLoaded', () => {
    searchForm.addEventListener('submit', handleSearch);
    loginButton.addEventListener('click', handleLogin);

    // Check if we have a token in localStorage
    const savedToken = localStorage.getItem('authToken');
    if (savedToken) {
        authToken = savedToken;
        updateAuthStatus(true);
    } else {
        // Auto login for testing purposes
        autoLogin();
    }
});

// Auto login function for testing
async function autoLogin() {
    try {
        const formData = new FormData();
        formData.append('username', 'admin');
        formData.append('password', 'password');

        const response = await fetch(`${API_BASE_URL}/auth/login`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error('Auto authentication failed');
        }

        const data = await response.json();
        authToken = data.access_token;

        // Save token to localStorage
        localStorage.setItem('authToken', authToken);

        updateAuthStatus(true, 'Auto authentication successful');
    } catch (error) {
        console.error('Auto login error:', error);
        updateAuthStatus(false, 'Auto login failed. Please login manually.');
    }
}

// Authentication Functions
async function handleLogin() {
    const username = usernameInput.value.trim();
    const password = passwordInput.value.trim();

    if (!username || !password) {
        updateAuthStatus(false, 'Username and password are required');
        return;
    }

    try {
        const formData = new FormData();
        formData.append('username', username);
        formData.append('password', password);

        const response = await fetch(`${API_BASE_URL}/auth/login`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error('Authentication failed');
        }

        const data = await response.json();
        authToken = data.access_token;

        // Save token to localStorage
        localStorage.setItem('authToken', authToken);

        updateAuthStatus(true, 'Authentication successful');
    } catch (error) {
        console.error('Login error:', error);
        updateAuthStatus(false, error.message || 'Authentication failed');
    }
}

function updateAuthStatus(isSuccess, message = '') {
    authStatus.textContent = message || (isSuccess ? 'Authenticated' : 'Not authenticated');
    authStatus.className = isSuccess ? 'auth-success' : 'auth-error';

    // Update UI based on auth status
    if (isSuccess) {
        loginButton.textContent = 'Logged In';
        loginButton.disabled = true;
    } else {
        loginButton.textContent = 'Login';
        loginButton.disabled = false;
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

    if (!authToken) {
        alert('Please login first');
        return;
    }

    // Show loading state
    resultsSection.style.display = 'block';
    loadingElement.style.display = 'block';
    resultsElement.style.display = 'none';

    try {
        // Get the selected search provider
        const searchProvider = searchProviderSelect.value;

        // Create headers with search provider preference
        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${authToken}`,
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
