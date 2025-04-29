// Configuration
const API_BASE_URL = 'http://localhost:8000/open-search-agent';
let apiKey = 'test_api_key_123'; // Default API key matching the one in backend/.env
// Last updated: 2025-04-28 22:50:00

// DOM Elements
const searchForm = document.getElementById('search-form');
const promptInput = document.getElementById('prompt');
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
    console.log('DOM loaded - script.js updated at 2025-04-28 23:00:00');

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
    resultsElement.style.display = 'block';

    // Clear previous results
    reportElement.innerHTML = '';
    stepsContainer.innerHTML = '';
    sourcesList.innerHTML = '';

    // Add status display
    const statusElement = document.createElement('div');
    statusElement.className = 'status-message';
    statusElement.textContent = 'Starting search...';
    stepsContainer.appendChild(statusElement);

    // Initialize report container
    reportElement.innerHTML = '<div class="report-loading">Generating report...</div>';

    try {
        // Create headers with Bearer token authentication only
        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${apiKey}`  // Use Bearer token authentication
        };

        // Use the streaming endpoint
        const response = await fetch(`${API_BASE_URL}/search/stream`, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({ prompt })
        });

        if (!response.ok) {
            throw new Error('Search request failed');
        }

        // Process the streaming response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let reportContent = '';
        let searchSteps = [];
        let sources = [];

        // Hide the spinner but keep the results section visible
        loadingElement.style.display = 'none';

        while (true) {
            const { done, value } = await reader.read();

            if (done) {
                break;
            }

            // Decode the chunk and add it to our buffer
            buffer += decoder.decode(value, { stream: true });

            // Process complete lines in the buffer
            let lineEnd;
            while ((lineEnd = buffer.indexOf('\n')) >= 0) {
                const line = buffer.slice(0, lineEnd);
                buffer = buffer.slice(lineEnd + 1);

                if (line.trim() === '') continue;

                try {
                    const event = JSON.parse(line);
                    processStreamEvent(event, statusElement);

                    // Collect data for final display
                    if (event.event === 'report_chunk') {
                        reportContent += event.data.content;
                        updateReportDisplay(reportContent);
                    } else if (event.event === 'search_query') {
                        // Add to search steps
                        const step = {
                            query: event.data.query,
                            sufficient: false,
                            reasoning: 'Processing...'
                        };
                        searchSteps.push(step);
                        updateSearchStepsDisplay(searchSteps);
                    } else if (event.event === 'evaluation') {
                        // Update the corresponding search step
                        const stepIndex = searchSteps.findIndex(s => s.query === event.data.query);
                        if (stepIndex >= 0) {
                            searchSteps[stepIndex].sufficient = event.data.sufficient;
                            searchSteps[stepIndex].reasoning = event.data.reasoning;
                            updateSearchStepsDisplay(searchSteps);
                        }
                    } else if (event.event === 'sources') {
                        sources = event.data.sources;
                        updateSourcesDisplay(sources);
                    }
                } catch (e) {
                    console.error('Error parsing stream event:', e, line);
                }
            }
        }

        // Process any remaining data in the buffer
        if (buffer.trim()) {
            try {
                const event = JSON.parse(buffer);
                processStreamEvent(event, statusElement);
            } catch (e) {
                console.error('Error parsing final stream event:', e, buffer);
            }
        }

        // Final update of the report with proper formatting
        if (reportContent) {
            updateReportDisplay(reportContent, true);
        }

    } catch (error) {
        console.error('Search error:', error);
        reportElement.innerHTML = `<div class="error">Error: ${error.message || 'Failed to perform search'}</div>`;
        statusElement.textContent = `Error: ${error.message || 'Failed to perform search'}`;
        statusElement.className = 'status-message error';
    } finally {
        loadingElement.style.display = 'none';
    }
}

// Process streaming events
function processStreamEvent(event, statusElement) {
    console.log('Stream event:', event.event, event.data);

    switch (event.event) {
        case 'search_start':
            statusElement.textContent = 'Search started...';
            break;

        case 'status':
            statusElement.textContent = event.data.message;
            break;

        case 'decomposed_queries':
            statusElement.textContent = `Decomposed into ${event.data.queries.length} search queries`;
            // Display the queries
            const queriesElement = document.createElement('div');
            queriesElement.className = 'decomposed-queries';
            queriesElement.innerHTML = '<h4>Search Queries:</h4><ul>' +
                event.data.queries.map(q => `<li>${escapeHTML(q)}</li>`).join('') +
                '</ul>';
            stepsContainer.appendChild(queriesElement);
            break;

        case 'search_query':
            statusElement.textContent = `Searching for: ${event.data.query}`;
            break;

        case 'search_results':
            statusElement.textContent = `Found ${event.data.count} results for: ${event.data.query}`;
            break;

        case 'summarize_progress':
            statusElement.textContent = `Summarizing result ${event.data.current}/${event.data.total} for query: ${event.data.query}`;
            break;

        case 'summarize_complete':
            statusElement.textContent = `Completed summarizing ${event.data.count} results for: ${event.data.query}`;
            break;

        case 'no_results':
            statusElement.textContent = `No results found for query: ${event.data.query}`;
            break;

        case 'error':
            statusElement.textContent = `Error: ${event.data.message}`;
            statusElement.className = 'status-message error';
            break;

        case 'search_complete':
            statusElement.textContent = 'Search completed';
            statusElement.className = 'status-message success';
            break;
    }
}

// Update the report display with streaming content
function updateReportDisplay(content, final = false) {
    if (final) {
        // Final update with full markdown formatting
        reportElement.innerHTML = formatMarkdown(content);
    } else {
        // Streaming update with basic formatting
        reportElement.innerHTML = `<div class="streaming-report">${content.replace(/\n/g, '<br>')}</div>`;
    }

    // Scroll to the bottom of the report
    reportElement.scrollTop = reportElement.scrollHeight;
}

// Update the search steps display
function updateSearchStepsDisplay(steps) {
    stepsContainer.querySelectorAll('.step').forEach(el => el.remove());

    steps.forEach(step => {
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
}

// Update the sources display
function updateSourcesDisplay(sources) {
    sourcesList.innerHTML = '';
    sources.forEach(source => {
        const sourceItem = document.createElement('li');
        sourceItem.innerHTML = `
            <a href="${escapeHTML(source.link)}" target="_blank">${escapeHTML(source.title)}</a>
            <p>${escapeHTML(source.snippet || source.summary || '')}</p>
        `;
        sourcesList.appendChild(sourceItem);
    });
}

function displayResults(data) {
    // Display the final report
    reportElement.innerHTML = formatMarkdown(data.final_report);

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
