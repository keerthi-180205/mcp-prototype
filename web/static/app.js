document.addEventListener('DOMContentLoaded', () => {
    const chatForm = document.getElementById('chatForm');
    const queryInput = document.getElementById('queryInput');
    const sendBtn = document.getElementById('sendBtn');
    const messagesContainer = document.getElementById('messagesContainer');
    const maxReelsInput = document.getElementById('maxReelsInput');
    const maxCommentsInput = document.getElementById('maxCommentsInput');
    const platformSelect = document.getElementById('platformSelect');
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
            const targetPlatform = btn.getAttribute('data-platform');
            if (targetPlatform && platformSelect) {
                platformSelect.value = targetPlatform;
            }
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

        const maxReels = parseInt(maxReelsInput ? maxReelsInput.value : 5) || 5;
        const maxComments = parseInt(maxCommentsInput ? maxCommentsInput.value : 25) || 25;

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
                addErrorMessage(data.message || `An error occurred while fetching social intelligence.`);
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
                            Universal Social Intelligence Pipeline Executing...
                        </h4>
                        <div class="pipeline-steps">
                            <div class="step-item active">
                                <span class="step-bullet"></span>
                                <span>Scanning reachable platforms via Agent Reach (YouTube, Reddit, X / Twitter, Instagram)...</span>
                            </div>
                            <div class="step-item active">
                                <span class="step-bullet"></span>
                                <span>Discovering top trending posts & videos...</span>
                            </div>
                            <div class="step-item active">
                                <span class="step-bullet"></span>
                                <span>Extracting commenter user IDs & exact public comments...</span>
                            </div>
                            <div class="step-item active">
                                <span class="step-bullet"></span>
                                <span>Ranking comments by engagement and deduplicating...</span>
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

    function getPlatformStyle(platform) {
        const p = (platform || '').toLowerCase();
        if (p.includes('youtube')) {
            return 'background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3);';
        } else if (p.includes('reddit')) {
            return 'background: rgba(249, 115, 22, 0.15); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.3);';
        } else if (p.includes('twitter') || p.includes(' x')) {
            return 'background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3);';
        } else if (p.includes('instagram')) {
            return 'background: rgba(236, 72, 153, 0.15); color: #f472b6; border: 1px solid rgba(236, 72, 153, 0.3);';
        }
        return 'background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3);';
    }

    function addAssistantResponse(data) {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message assistant-message';

        const comments = data.comments || [];
        const totalComments = comments.length;
        const reachedStr = data.platform || (data.platforms_reached ? data.platforms_reached.join(', ') : 'Universal Reach');

        let tableBodyHtml = '';
        if (comments.length === 0) {
            tableBodyHtml = `
                <tr>
                    <td colspan="4" style="padding: 24px; text-align: center; color: #94a3b8;">
                        No public comments found across reachable platforms. Try a broader topic term.
                    </td>
                </tr>
            `;
        } else {
            tableBodyHtml = comments.map(c => {
                const userId = c.user_id || c.username || 'anonymous';
                const commentText = c.comment || c.comment_text || '';
                const platformName = c.platform || 'Social';
                const sourceUrl = c.link || c.post_url || '';
                const badgeStyle = getPlatformStyle(platformName);

                return `
                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.06);">
                        <td style="padding: 10px 14px; font-weight: 600; color: #93c5fd; white-space: nowrap; vertical-align: top;">
                            ${escapeHtml(userId)}
                            ${c.likes > 0 ? `<div style="font-size: 0.72rem; color: #64748b; font-weight: normal; margin-top: 2px;">❤️ ${c.likes.toLocaleString()} likes</div>` : ''}
                        </td>
                        <td style="padding: 10px 14px; line-height: 1.5; color: #e2e8f0; vertical-align: top;">
                            ${escapeHtml(commentText)}
                        </td>
                        <td style="padding: 10px 14px; text-align: center; vertical-align: top; white-space: nowrap;">
                            <span style="display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; ${badgeStyle}">
                                ${escapeHtml(platformName)}
                            </span>
                        </td>
                        <td style="padding: 10px 14px; text-align: center; vertical-align: top; white-space: nowrap;">
                            ${sourceUrl ? `
                                <a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer" style="display: inline-flex; align-items: center; gap: 4px; color: #60a5fa; background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.25); padding: 3px 8px; border-radius: 6px; font-size: 0.75rem; text-decoration: none;">
                                    View Source ↗
                                </a>
                            ` : '<span style="color: #64748b; font-size: 0.75rem;">N/A</span>'}
                        </td>
                    </tr>
                `;
            }).join('');
        }

        msgDiv.innerHTML = `
            <div class="avatar">AI</div>
            <div class="message-content" style="max-width: 100%;">
                <div class="message-bubble" style="max-width: 100%;">
                    <p style="font-size: 0.95rem; margin-bottom: 12px;">
                        ${escapeHtml(data.chatbot_message || `Collected ${totalComments} public comments across ${reachedStr}:`)}
                    </p>

                    <div style="overflow-x: auto; background: rgba(15, 23, 42, 0.7); border-radius: 10px; border: 1px solid var(--border);">
                        <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem; color: #cbd5e1;">
                            <thead>
                                <tr style="border-bottom: 1px solid var(--border); background: rgba(0,0,0,0.3); text-align: left;">
                                    <th style="padding: 10px 14px; width: 180px;">User ID</th>
                                    <th style="padding: 10px 14px;">Comment</th>
                                    <th style="padding: 10px 14px; text-align: center; width: 130px;">Platform Name</th>
                                    <th style="padding: 10px 14px; text-align: center; width: 140px;">Source Link</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${tableBodyHtml}
                            </tbody>
                        </table>
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
        const headers = ['Username', 'User ID', 'Comment Text', 'Category', 'Likes', 'Post URL', 'Timestamp'];
        const rows = records.map(r => [
            `"${(r.user_handle || r.username || '').replace(/"/g, '""')}"`,
            `"${(r.user_id || '').replace(/"/g, '""')}"`,
            `"${(r.comment_text || r.comment || '').replace(/"/g, '""')}"`,
            `"${(r.category || '').replace(/"/g, '""')}"`,
            r.likes || 0,
            `"${(r.post_url || '').replace(/"/g, '""')}"`,
            `"${(r.created_at || '').replace(/"/g, '""')}"`,
        ]);

        const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(e => e.join(','))].join('\n');
        const encodedUri = encodeURI(csvContent);
        const link = document.createElement('a');
        link.setAttribute('href', encodedUri);
        link.setAttribute('download', `social_comments_${Date.now()}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }
});
