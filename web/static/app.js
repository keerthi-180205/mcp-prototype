document.addEventListener('DOMContentLoaded', () => {
    const chatForm = document.getElementById('chatForm');
    const queryInput = document.getElementById('queryInput');
    const sendBtn = document.getElementById('sendBtn');
    const messagesContainer = document.getElementById('messagesContainer');
    const maxReelsInput = document.getElementById('maxReelsInput');
    const maxCommentsInput = document.getElementById('maxCommentsInput');
    const exportCsvBtn = document.getElementById('exportCsvBtn');

    let allExtractedRecords = [];

    // Auto resize textarea
    queryInput.addEventListener('input', () => {
        queryInput.style.height = 'auto';
        queryInput.style.height = `${Math.min(queryInput.scrollHeight, 120)}px`;
    });

    queryInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event('submit'));
        }
    });

    // Preset Buttons Click
    document.querySelectorAll('.preset-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const query = btn.getAttribute('data-query');
            queryInput.value = query;
            queryInput.dispatchEvent(new Event('input'));
            chatForm.dispatchEvent(new Event('submit'));
        });
    });

    // Export CSV
    exportCsvBtn.addEventListener('click', () => {
        if (!allExtractedRecords.length) return;
        exportToCsv(allExtractedRecords);
    });

    // Form Submit
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const query = queryInput.value.trim();
        if (!query) return;

        const maxReels = parseInt(maxReelsInput.value) || 2;
        const maxComments = parseInt(maxCommentsInput.value) || 10;

        // Add user message
        addUserMessage(query);
        queryInput.value = '';
        queryInput.style.height = 'auto';

        // Add thinking / pipeline progress message
        const thinkingId = addThinkingMessage();
        setSendLoading(true);

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    query: query,
                    max_reels: maxReels,
                    max_comments_per_reel: maxComments,
                }),
            });

            const data = await response.json();
            removeMessage(thinkingId);

            if (data.status === 'success') {
                addAssistantResponse(data);
                if (data.comments && data.comments.length) {
                    allExtractedRecords = [...allExtractedRecords, ...data.comments];
                    exportCsvBtn.style.display = 'flex';
                }
            } else {
                addErrorMessage(data.message || 'An error occurred while fetching Instagram intelligence.');
            }
        } catch (err) {
            removeMessage(thinkingId);
            addErrorMessage(`Connection failed: ${err.message}. Please check if the web server is running.`);
        } finally {
            setSendLoading(false);
            scrollToBottom();
        }
    });

    function addUserMessage(text) {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message user-message';
        msgDiv.innerHTML = `
            <div class="avatar">You</div>
            <div class="message-content">
                <div class="message-bubble">
                    <p>${escapeHtml(text)}</p>
                </div>
            </div>
        `;
        messagesContainer.appendChild(msgDiv);
        scrollToBottom();
    }

    function addThinkingMessage() {
        const id = 'thinking-' + Date.now();
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message assistant-message';
        msgDiv.id = id;
        msgDiv.innerHTML = `
            <div class="avatar">AI</div>
            <div class="message-content">
                <div class="message-bubble">
                    <div class="pipeline-card">
                        <h4>
                            <span class="spinner"></span>
                            Agent Reach & Apify Pipeline Executing...
                        </h4>
                        <div class="pipeline-steps">
                            <div class="step-item active">
                                <span class="step-bullet"></span>
                                <span>Discovering relevant public Instagram Reels (stress, anxiety, pressure)...</span>
                            </div>
                            <div class="step-item active">
                                <span class="step-bullet"></span>
                                <span>Navigating into comment sections of discovered reels...</span>
                            </div>
                            <div class="step-item active">
                                <span class="step-bullet"></span>
                                <span>Extracting commenter user handles & exact comment texts...</span>
                            </div>
                            <div class="step-item active">
                                <span class="step-bullet"></span>
                                <span>Filtering mental-health relevant discussions & storing in SQLite...</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        messagesContainer.appendChild(msgDiv);
        scrollToBottom();
        return id;
    }

    function addAssistantResponse(data) {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message assistant-message';

        const comments = data.comments || [];
        const reelsCount = data.reels_analyzed || 0;
        const totalComments = comments.length;

        let cardsHtml = '';
        if (comments.length === 0) {
            cardsHtml = `
                <div style="padding: 16px; background: rgba(0,0,0,0.2); border-radius: 8px; color: #94a3b8; font-size: 0.88rem;">
                    No public comments specifically matching mental health discussions were returned for this query. Try a different topic or verify your Apify token.
                </div>
            `;
        } else {
            cardsHtml = comments.map(c => {
                const badgeClass = getBadgeClass(c.category);
                const profileUrl = c.user_handle 
                    ? `https://www.instagram.com/${c.user_handle}/` 
                    : (c.profile_url || '#');

                return `
                    <div class="comment-card">
                        <div class="comment-header">
                            <div class="insta-user">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#f472b6" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"></path><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"></line></svg>
                                <a href="${profileUrl}" target="_blank" rel="noopener noreferrer" class="insta-handle">
                                    @${escapeHtml(c.user_handle || 'anonymous_user')}
                                </a>
                                ${c.is_verified ? '<span class="verified-badge" title="Verified">✓</span>' : ''}
                                ${c.user_id ? `<span style="font-size: 0.68rem; color: #64748b;">(ID: ${c.user_id})</span>` : ''}
                            </div>
                            <span class="topic-badge ${badgeClass}">${escapeHtml(c.category || 'Mental Health')}</span>
                        </div>

                        <div class="comment-body">
                            "${escapeHtml(c.comment_text)}"
                        </div>

                        <div class="comment-footer">
                            <span>❤️ ${c.likes || 0} likes &bull; ${c.created_at || 'Recent'}</span>
                            <a href="${c.post_url}" target="_blank" rel="noopener noreferrer" class="source-link">
                                Source Reel ↗
                            </a>
                        </div>
                    </div>
                `;
            }).join('');
        }

        msgDiv.innerHTML = `
            <div class="avatar">AI</div>
            <div class="message-content">
                <div class="message-bubble">
                    <p style="font-size: 0.95rem; margin-bottom: 12px;">
                        ${escapeHtml(data.summary_message || 'Here are the acquired Instagram mental health comments:')}
                    </p>

                    <div class="results-summary">
                        <div class="stat-chip">
                            <span>Reels Analyzed</span>
                            <strong>${reelsCount}</strong>
                        </div>
                        <div class="stat-chip">
                            <span>Commenters Extracted</span>
                            <strong>${totalComments}</strong>
                        </div>
                        <div class="stat-chip">
                            <span>Target Filter</span>
                            <strong style="color: #f472b6;">Mental Health</strong>
                        </div>
                    </div>

                    <div class="comments-stream">
                        ${cardsHtml}
                    </div>
                </div>
            </div>
        `;

        messagesContainer.appendChild(msgDiv);
        scrollToBottom();
    }

    function addErrorMessage(errorText) {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message assistant-message';
        msgDiv.innerHTML = `
            <div class="avatar" style="background: #ef4444;">!</div>
            <div class="message-content">
                <div class="message-bubble" style="border-color: #ef4444;">
                    <p style="color: #fca5a5;"><strong>Error during intelligence acquisition:</strong></p>
                    <p style="font-size: 0.88rem; margin-top: 6px;">${escapeHtml(errorText)}</p>
                </div>
            </div>
        `;
        messagesContainer.appendChild(msgDiv);
        scrollToBottom();
    }

    function removeMessage(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    function setSendLoading(isLoading) {
        sendBtn.disabled = isLoading;
        sendBtn.innerHTML = isLoading 
            ? '<span class="spinner"></span>'
            : `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>`;
    }

    function scrollToBottom() {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function getBadgeClass(category) {
        if (!category) return 'anxiety';
        const lower = category.toLowerCase();
        if (lower.includes('work') || lower.includes('burnout')) return 'work';
        if (lower.includes('exam') || lower.includes('study')) return 'exam';
        if (lower.includes('stress')) return 'stress';
        return 'anxiety';
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function exportToCsv(records) {
        const headers = ['Instagram Username', 'User ID', 'Comment Text', 'Category', 'Likes', 'Reel URL', 'Timestamp'];
        const rows = records.map(r => [
            `"${(r.user_handle || '').replace(/"/g, '""')}"`,
            `"${(r.user_id || '').replace(/"/g, '""')}"`,
            `"${(r.comment_text || '').replace(/"/g, '""')}"`,
            `"${(r.category || '').replace(/"/g, '""')}"`,
            r.likes || 0,
            `"${(r.post_url || '').replace(/"/g, '""')}"`,
            `"${(r.created_at || '').replace(/"/g, '""')}"`,
        ]);

        const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(e => e.join(','))].join('\n');
        const encodedUri = encodeURI(csvContent);
        const link = document.createElement('a');
        link.setAttribute('href', encodedUri);
        link.setAttribute('download', `instagram_mental_health_comments_${Date.now()}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }
});
